def GetVersion(): return 4

Nb = 4 #Кол-во столбцов State по 4байта
Nk = 4 #Длина ключа по 4байта
Nr = Nk+6 #Кол-во раундов шифрования

sbox = [
  99,124,119,123,242,107,111,197,48,1,103,43,254,215,171,118,
  202,130,201,125,250,89,71,240,173,212,162,175,156,164,114,192,
  183,253,147,38,54,63,247,204,52,165,229,241,113,216,49,21,
  4,199,35,195,24,150,5,154,7,18,128,226,235,39,178,117,
  9,131,44,26,27,110,90,160,82,59,214,179,41,227,47,132,
  83,209,0,237,32,252,177,91,106,203,190,57,74,76,88,207,
  208,239,170,251,67,77,51,133,69,249,2,127,80,60,159,168,
  81,163,64,143,146,157,56,245,188,182,218,33,16,255,243,210,
  205,12,19,236,95,151,68,23,196,167,126,61,100,93,25,115,
  96,129,79,220,34,42,144,136,70,238,184,20,222,94,11,219,
  224,50,58,10,73,6,36,92,194,211,172,98,145,149,228,121,
  231,200,55,109,141,213,78,169,108,86,244,234,101,122,174,8,
  186,120,37,46,28,166,180,198,232,221,116,31,75,189,139,138,
  112,62,181,102,72,3,246,14,97,53,87,185,134,193,29,158,
  225,248,152,17,105,217,142,148,155,30,135,233,206,85,40,223,
  140,161,137,13,191,230,66,104,65,153,45,15,176,84,187,22
]
dsbox = [sbox.index(i) for i in range(256)]

KeyC = None

# старый вариант:
def mul_by_02(num):
  if num < 128: return num * 2
  return ((num * 2) ^ 27) & 255
def mul_by_03(num): return mul_by_02(num)^num
def mul_by_09(num): return mul_by_02(mul_by_02(mul_by_02(num)))^num
def mul_by_0b(num): return mul_by_02(mul_by_02(mul_by_02(num)))^mul_by_02(num)^num
def mul_by_0d(num): return mul_by_02(mul_by_02(mul_by_02(num)))^mul_by_02(mul_by_02(num))^num
def mul_by_0e(num): return mul_by_02(mul_by_02(mul_by_02(num)))^mul_by_02(mul_by_02(num))^mul_by_02(num)

# print(tuple(mul_by_0e(num) for num in range(256)))

# новый вариант:
mul_by_02 = bytes(num * 2 if num < 128 else (num * 2 ^ 27) & 255 for num in range(256))
mul_by_04 = bytes(mul_by_02[mul_by_02[num]] for num in range(256))
mul_by_08 = bytes(mul_by_04[mul_by_02[num]] for num in range(256)) # mul_by_04[mul_by_02[num] == mul_by_02[mul_by_04[num]

mul_by_03 = bytes(mul_by_02[num] ^ num for num in range(256))
mul_by_09 = bytes(mul_by_08[num] ^ num for num in range(256))
mul_by_0b = bytes(mul_by_08[num] ^ mul_by_02[num] ^ num for num in range(256))
mul_by_0d = bytes(mul_by_08[num] ^ mul_by_04[num] ^ num for num in range(256))
mul_by_0e = bytes(mul_by_08[num] ^ mul_by_04[num] ^ mul_by_02[num] for num in range(256))

def check_mul_by():
    for name, value in globals().copy().items():
        if name.startswith("mul_by_"):
            print(f"~~~\n{name}: {value}")
            assert len(value) == 256 and len(set(value)) == 256 # не должно быть повторяшек!

rcon = [[], [0] * 50, [0] * 50, [0] * 50]
N = 1
for i in range(50):
  rcon[0].append(N)
  N = mul_by_02[N]

def MixColumns(state,R):
  for i in range(Nb):
    if R:
      s0 = mul_by_0e[state[0][i]]^mul_by_0b[state[1][i]]^mul_by_0d[state[2][i]]^mul_by_09[state[3][i]]
      s1 = mul_by_09[state[0][i]]^mul_by_0e[state[1][i]]^mul_by_0b[state[2][i]]^mul_by_0d[state[3][i]]
      s2 = mul_by_0d[state[0][i]]^mul_by_09[state[1][i]]^mul_by_0e[state[2][i]]^mul_by_0b[state[3][i]]
      s3 = mul_by_0b[state[0][i]]^mul_by_0d[state[1][i]]^mul_by_09[state[2][i]]^mul_by_0e[state[3][i]]
    else:
      s0 = mul_by_02[state[0][i]]^mul_by_03[state[1][i]]^state[2][i]^state[3][i]
      s1 = state[0][i]^mul_by_02[state[1][i]]^mul_by_03[state[2][i]]^state[3][i]
      s2 = state[0][i]^state[1][i]^mul_by_02[state[2][i]]^mul_by_03[state[3][i]]
      s3 = mul_by_03[state[0][i]]^state[1][i]^state[2][i]^mul_by_02[state[3][i]]
    state[0][i] = s0
    state[1][i] = s1
    state[2][i] = s2
    state[3][i] = s3
  return state

def ShiftRows(state,R):
  for i in range(1,4):
    for j in range(i,4):
      if R: state[i] = state[i][1:] + [state[i][0]]
      else: state[i] = [state[i][-1]] + state[i][:-1]
  return state

def SybBytes(state,R):
  for j in range(4):
    for i in range(Nb):
      if R: state[j][i] = dsbox[state[j][i]]
      else: state[j][i] = sbox[state[j][i]]
  return state

def KeyExpansion(Key):
  KeyS = Key
  #KeyS = [ord(S) for S in Key]
  if len(KeyS) < 4 * Nk:
    for i in range(4*Nk - len(KeyS)): KeyS.append(1)
  KeyC = [[] for i in range(4)]   
  for r in range(4):
    for c in range(Nk): KeyC[r].append(KeyS[r + 4 * c])
  for col in range(Nk, Nb*(Nr + 1)):
    if col % Nk == 0:
      tmp = [KeyC[row][col-1] for row in range(1,4)]
      tmp.append(KeyC[0][col-1])
      for j in range(len(tmp)): tmp[j] = sbox[tmp[j]]
      for row in range(4): KeyC[row].append(KeyC[row][col - Nk]^tmp[row]^rcon[row][int(col/Nk - 1)])
    else:
      for row in range(4): KeyC[row].append(KeyC[row][col - Nk]^KeyC[row][col - 1])
  #for i in range(Nb*(Nr + 1)):
  #  if i % Nk == 0: print("_" * 20)
  #  print(KeyC[0][i], KeyC[1][i], KeyC[2][i], KeyC[3][i])
  return KeyC
#KeyExpansion([])

def AddRoundKey(state, round):
  for col in range(Nk):
    for row in range(4):
      state[row][col] = state[row][col]^KeyC[row][Nb*round + col]
  return state

def CoderAES(block, R):
  state = [[block[r + 4 * c] for c in range(Nb)] for r in range(4)]
  
  if R:
    state = AddRoundKey(state, Nr)
    state = ShiftRows(state,True)
    state = SybBytes(state,True)
    for i in range(Nr-1, 0, -1):
      state = AddRoundKey(state, i)
      state = MixColumns(state,True)
      state = ShiftRows(state,True)
      state = SybBytes(state,True)
    state = AddRoundKey(state, 0)
  else:
    state = AddRoundKey(state, 0)
    for i in range(1,Nr):
      state = SybBytes(state,False)
      state = ShiftRows(state,False)
      state = MixColumns(state,False)
      state = AddRoundKey(state, i)
    state = SybBytes(state,False)
    state = ShiftRows(state,False)
    state = AddRoundKey(state, Nr)
  
  return [state[rc % 4][rc // 4] for rc in range(16)]

def Hex(Zn,Tr=True):
  if Tr: Zn = Zn[0]+Zn[1]+Zn[2]+Zn[3]
  tab = "0123456789abcdef"
  Str = ""
  for i in Zn: Str += tab[i // 16] + tab[i % 16]
  return Str
def InvHex(Hex):
  Hex = Hex.lower()
  tab = "0123456789abcdef"
  bytes = []
  for i in range(len(Hex) // 2):
    Block = Hex[i*2:(i+1)*2]
    bytes.append(tab.index(Block[0])*16+tab.index(Block[1]))
  return bytes

def DecoderAES(data):
  Str = b""
  LD = len(data) // 32
  for i in range(LD):
    Zn = data[i*32:(i+1)*32]
    Zn = CoderAES(InvHex(Zn), True)
    Str += bytes(Zn)
  ESim = Str[-1]
  if ESim <= 16:
    Raz = True
    for i in range(1,ESim+1):
      if Str[-i] != ESim: Raz = False
    if Raz: Str = Str[:-ESim]
  try: return Str.decode("utf-8")
  except: return Hex(Str,False).upper()

def EncoderAES(data):
  if type(data) == str: data = data.encode("utf-8")
  if type(data) == bytes: data = list(data)
  
  Dop = (16-len(data) % 16)
  data += [Dop] * Dop
  Str = ""
  for i in range(len(data)//16):
    Zn = data[i*16:(i+1)*16]
    Zn = CoderAES(Zn, False)
    Str += Hex(Zn, False)
  return Str

def SetKey(key, hex):
  global KeyC
  if hex: key = InvHex(key)
  KeyC = KeyExpansion(key)

#SetKey("a0428e4bc328e248c98a839cf82f983a", True)
#Str = EncoderAES("LOLOS")
#Str2 = DecoderAES(Str)
#print(Str, Str2)
