function assert(condition, message) {
    if (!condition)
        throw new Error(message || "Assertion failed");
}
function generate(node) {
    return Babel.packages.generator.default(node).code;
}
function recalc_bindings(ast) {
    Babel.packages.traverse.default(ast, {
        Program(path) {
            path.scope.crawl();
        }
    });
}

function replaceUndefinedWithVoid(node) {
    // We use this so that `undefined` doesn't break isPure in arrays
    const t = Babel.packages.types;
    if (node == null) return node;
    if (node.type === 'Identifier' && node.name === 'undefined') {
        return t.unaryExpression('void', t.numericLiteral(0));
    }
    for (const key of Object.keys(node)) {
        // Skip non-AST fields
        if (['loc', 'start', 'end', 'leadingComments', 'trailingComments'].includes(key)) continue;
        const val = node[key];
        if (Array.isArray(val))
            node[key] = val.map(item => replaceUndefinedWithVoid(item));
        else if (val && typeof val.type === 'string')
            node[key] = replaceUndefinedWithVoid(val);
    }
    return node;
}
function ConstantFolding(ast) {
    const types = new Set();
    const replacements = [];
    const t = Babel.packages.types;
    Babel.packages.traverse.default(ast, {
        enter(path) {
            if (!path.isLiteral() && path.isExpression()) {
                const result = path.evaluate();
                if (result.confident) {
                    const replacementNode = t.valueToNode(result.value);
                    const safeReplacementNode = replaceUndefinedWithVoid(replacementNode);
                    if (!t.isNodesEquivalent(path.node, safeReplacementNode)) {
                     // console.log(generate(path.node), path.node.type, result.value);
                        types.add(path.node.type);
                        replacements.push([path, safeReplacementNode]);
                        path.skip();  // skip children, we will replace the whole node
                    }
                }
            }
        }
    });
    console.log(replacements.length, types);
    for (const [path, replacementNode] of replacements)
        path.replaceWith(replacementNode);
}

function ArrayUnpacking(ast, funcName, varName) {
    // My first Babel pass :)
    let func;
    Babel.packages.traverse.default(ast, {
        FunctionDeclaration(path) {
            if (path.node.id.name == funcName) {
                func = path;
                path.stop();
            }
        }
    });
    assert(func !== void 0);

    const bindings = [], references = [];
    func.traverse({
        Identifier(innerPath) {
            if (innerPath.node.name === varName) {
                const isBinding = innerPath.isBindingIdentifier();
                const isReference = innerPath.isReferencedIdentifier();
                if (isBinding)
                    bindings.push(innerPath.parent);
                else if (isReference)
                    references.push(innerPath.parentPath);
            }
        }
    });
    assert(bindings.length == 1);
    assert(bindings[0].type == "VariableDeclarator");
    assert(bindings[0].init.type == "ArrayExpression");

    const counter = new Map();
    const arrItems = bindings[0].init.elements;
    const t = Babel.packages.types;
    function isVoid(item) {
        return t.isUnaryExpression(item, { operator: "void" })
            && t.isNumericLiteral(item.argument, { value: 0 });
    }
    for (const item of arrItems) {
        counter.set(item.type, (counter.get(item.type) || 0) + 1);
        assert(t.isLiteral(item) || item.type == "Identifier" || isVoid(item));
    }
    console.log(counter);

    function getItem(node) {
        assert(node.type == "MemberExpression");
        assert(node.object.type == "Identifier");
        assert(node.object.name == varName);
        if (node.property.type == "NumericLiteral")
            return arrItems[node.property.value];

        const property = getItem(node.property);
        assert(property.type == "NumericLiteral");
        return arrItems[property.value];
    }
    for (const path of references)
        path.replaceWith(getItem(path.node));
}

function ArrayUnpacking_v2(ast) {
    const t = Babel.packages.types;
    recalc_bindings(ast);

    Babel.packages.traverse.default(ast, {
        VariableDeclarator(innerPath) {
            const binding = innerPath.scope.getBinding(innerPath.node.id.name);
            if (!binding || !binding.constant || binding.references === 0) return;

            const init = innerPath.get("init");
            if (!init.isArrayExpression()) return;

            // The array must be pure (already ensured by ConstantFolding)
            if (!init.isPure()) return;

            const varName = innerPath.node.id.name;
            const elements = init.node.elements;
            const references = binding.referencePaths;

            function checkItem(node) {
                if (node.type !== "MemberExpression") return false;
                if (node.object.type !== "Identifier" || node.object.name !== varName) return false;
                if (node.property.type === "NumericLiteral") return true;
                return checkItem(node.property);
            }
            function getItem(node) {
                if (node.property.type === "NumericLiteral") {
                    return elements[node.property.value];
                }
                const inner = getItem(node.property);
                return elements[inner.value];
            }
            for (const path of references)
                if (!checkItem(path.parentPath.node))
                    return;

         // console.log("ok:", generate(innerPath.node));
            const counter = new Map();
            function isVoid(item) {
                return t.isUnaryExpression(item, { operator: "void" })
                    && t.isNumericLiteral(item.argument, { value: 0 });
            }
            for (const item of elements) {
                counter.set(item.type, (counter.get(item.type) || 0) + 1);
                assert(t.isLiteral(item) || item.type == "Identifier" || isVoid(item));
            }
            console.log(counter);

            for (const path of references)
                path.parentPath.replaceWith(getItem(path.parentPath.node));
        }
    });
}

function MemberExpressionToDot(ast) {
    const t = Babel.packages.types;
    Babel.packages.traverse.default(ast, {
        MemberExpression(path) {
            const node = path.node;
            if (node.computed && node.property.type === "StringLiteral") {
                const propName = node.property.value;
                if (t.isValidIdentifier(propName, false)) {
                    node.property = t.identifier(propName);
                    node.computed = false;
                }
            }
        }
    });
}

function isPatternUnused(path) {
    const id = path.node.id;
    if (id.type === "Identifier") {
        const binding = path.scope.getBinding(id.name);
        return !binding || binding.references === 0;
    }
    /*
    if (path.node.id.type === "ArrayPattern") {
        const names = Object.keys(path.getBindingIdentifiers());
        const refs = names.map(name => {
            const binding = path.scope.getBinding(name);
            return `${name}: ${binding ? binding.references : 0}`;
        });
        console.log("PATTERN:", generate(path.node), "=>", refs.join(", "));
    } */
    if (id.type === "ArrayPattern" || id.type === "ObjectPattern") {
        // Get all binding identifiers from the pattern
        const bindingIdentifiers = path.getBindingIdentifiers();
        for (const name of Object.keys(bindingIdentifiers)) {
            const binding = path.scope.getBinding(name);
            if (binding && binding.references > 0)
                return false;
        }
        return true;
    }
    return false;
}
function RemoveUnusedVariables(ast) {
    recalc_bindings(ast);
    Babel.packages.traverse.default(ast, {
        VariableDeclarator(path) {
            if (!isPatternUnused(path))
                return;

            const initPath = path.get('init');
            if (initPath && !initPath.isPure())
                return;

            console.log("REMOVE!", generate(path.node));
            path.remove();
            const parent = path.parentPath;
            if (parent.isVariableDeclaration() && parent.node.declarations.length === 0)
                parent.remove();
        }
    });
}

function isRegExpNewlineSource(objectPath) {
    // Identifier referencing a variable with a single assignment to new RegExp("\n")
    if (objectPath.isIdentifier()) {
        const binding = objectPath.scope.getBinding(objectPath.node.name);
        if (binding && binding.constant && binding.path.isVariableDeclarator()) {
            const init = binding.path.get('init');
            objectPath = init;
        }
    }
    // Direct call: new RegExp("\n")
    if (objectPath.isNewExpression()) {
        const callee = objectPath.get('callee');
        if (
            callee.isIdentifier({ name: 'RegExp' }) &&
            objectPath.get('arguments').length === 1 &&
            objectPath.get('arguments')[0].isStringLiteral({ value: '\n' })
        ) {
            return true;
        }
    }
    return false;
}
function isFunctionReference(argPath) {
    if (argPath.isFunctionExpression() || argPath.isArrowFunctionExpression()) {
        return true;
    }
    if (argPath.isIdentifier()) {
        const binding = argPath.scope.getBinding(argPath.node.name);
        if (binding) {
            if (binding.path.isFunctionDeclaration()) {
                return true;
            }
            if (binding.path.isVariableDeclarator()) {
                const init = binding.path.get('init');
                return init.isFunctionExpression() || init.isArrowFunctionExpression();
            }
        }
    }
    return false;
}
function RemoveAntiFormattingTraps(ast) {
    recalc_bindings(ast);
    const t = Babel.packages.types;
    Babel.packages.traverse.default(ast, {
        CallExpression(path) {
            const callee = path.get('callee');
            if (
                callee.isMemberExpression() &&
                callee.get('property').isIdentifier({ name: 'test' }) &&
                isRegExpNewlineSource(callee.get('object')) &&
                path.get('arguments').length >= 1 &&
                isFunctionReference(path.get('arguments')[0])
            ) {
                console.log("DETECTED!");
                path.replaceWith(t.booleanLiteral(false));
            }
        },
        IfStatement(path) {
            const test = path.get('test');
            if (test.isBooleanLiteral({ value: false })) {
                if (!path.node.alternate)
                    path.remove();
                else
                    path.replaceWith(path.node.alternate);
            }
        }
    });
}

function ReplaceInfiniteLoops(ast) {
    const t = Babel.packages.types;
    let loopCounter = 0;

    Babel.packages.traverse.default(ast, {
        WhileStatement(path) {
            const test = path.get('test');
            if (!test.isBooleanLiteral({ value: true })) return;

            // Check that the body is empty (or only an empty statement)
            const body = path.get('body');
            const bodyNode = body.node;
            const isEmpty = 
                bodyNode.type === 'BlockStatement' && bodyNode.body.length === 0 ||
                bodyNode.type === 'EmptyStatement';

            // Skip if the body contains any code
            if (!isEmpty) return;

            loopCounter++;
            const errorMessage = `Infinity loop №${loopCounter}`;
            const throwStatement = t.throwStatement(
                t.newExpression(
                    t.identifier('Error'),
                    [t.stringLiteral(errorMessage)]
                )
            );
            path.replaceWith(throwStatement);
            path.skip();
        }
    });
}

function debug_pipeline() {
    const code = `
(function () {
  var n = function () {
    const r = function () {
      const r = new RegExp("\\n");
      return r.test(n);
    };
    if (r()) {
      while (true) {}
    }
  };
  return n();
})();`;
    const ast = Babel.packages.parser.parse(code, {sourceType: "script"});
    RemoveAntiFormattingTraps(ast);

    console.log(generate(ast));
}

window.target_code ||= await (await fetch("challenge.js")).text();
function pipeline() {
    const code = window.target_code;
    const ast = Babel.packages.parser.parse(code, {sourceType: "script"});

    ConstantFolding(ast);  // 53
 // ConstantFolding(ast);  // 0
    ArrayUnpacking_v2(ast);
    ConstantFolding(ast);  // 828
    MemberExpressionToDot(ast);
    RemoveUnusedVariables(ast);
    RemoveAntiFormattingTraps(ast);
    ReplaceInfiniteLoops(ast);
 // ConstantFolding(ast);  // 0

    console.log(generate(ast));
}
pipeline();
