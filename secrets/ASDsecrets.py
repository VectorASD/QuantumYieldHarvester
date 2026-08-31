# Source: https://github.com/VectorASD/Magistracy/blob/main/1%20семестр/Методы%20сбора%20и%20обработки%20данных%20в%20сети%20Интернет/

from hashlib import sha256, pbkdf2_hmac
import struct
from time import time
import os
import sys
import pickle
from random import randint
from typing import Any

from . import ASDcoderAES  # written by me back in 2019, optimized in 2021
from . import mygram       # same AES, but with outstanding optimization from Telegram developers! Bonus: ige256, cbc256, TDF-reader and KeyFile-reader

ASDcoderAES.Nr = 14  # originally 10; changed to 14 because in Java and elsewhere it's configured this way...


def test():
    password = "MeowMeowMeow!"
    key = sha256(password.encode("utf-8")).digest()
    assert len(key) == 32  # exactly the length required for AES

    # eK -> expandedKey
    eK1 = ASDcoderAES.KeyExpansion(key)
    eK2 = mygram.aes256_set_encryption_key(key)
    ek3 = mygram.aes256_set_decryption_key(eK2, is_eK = True)
    assert ek3 == mygram.aes256_set_decryption_key(key)

    viewA = tuple(zip(*eK1))
    viewB = tuple(tuple(struct.pack(">I", num)) for num in eK2)
    print(len(viewA), len(viewB))  # 60 60
    print(viewA)
    print(viewB)
    # conclusion: they still produce different KeyExpansion... Though the beginning looks similar
    # they somehow managed to bake the sbox directly into the key!

    T1 = time()

    ASDcoderAES.KeyC = eK1
    encoded = ASDcoderAES.EncoderAES("test message")
    decoded = ASDcoderAES.DecoderAES(encoded)
    print("encoded:", encoded)  # bfed357e69d4d1ff0e95909eee3e9a59
    print("decoded:", decoded)  # test message

    T2 = time()

    text = "test message".encode("utf-8")
    pad = 16 - len(text) & 15
    text += bytes((pad,)) * pad

    encoded = mygram.aes256_encrypt(text,    eK2)
    decoded = mygram.aes256_decrypt(encoded, ek3)
    print("tg encoded:", encoded.hex())  # e470bdff5ea010dee96a2af48aaf2f91
    print("tg decoded:", decoded[:-decoded[-1]].decode("utf-8"))  # test message
    # conclusion: although both use AES with 14 rounds, they are somehow different...

    T3 = time()

    iv = b"\0" * 16
    assert mygram.cbc256(text, key, iv, True) == encoded

    print("my AES:", T2 - T1)  # 0.017785310745239258
    print("tg AES:", T3 - T2)  # 0.018413782119750977, i.e. slightly slower?!?!?!?!?


def get_appdata_path() -> str:
    if sys.platform.startswith("win"):
        # On Windows use the APPDATA environment variable
        return os.environ.get("APPDATA", os.path.expanduser(r"~\AppData\Roaming"))
    else:
        # On Linux/macOS, ~/.config is the common choice
        return os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))

class Storage:
    def __init__(self, name: str, force: bool = True):
        self.force = force
        self.salt = None

        appdata = get_appdata_path()
        workdir = os.path.join(appdata, "ASD_storage")
        os.makedirs(workdir, exist_ok=True)
        self.path = os.path.join(workdir, name)
        self.pw_base = {}
        self.load_passwords()

    def password_to_ek(self, password: str) -> list[int]:
        if self.force:
            salt = self.salt
            if salt is None:
                salt = self.salt = os.urandom(32)
            key = pbkdf2_hmac("sha256", (password + "Силовиковые силовики").encode("utf-8") * 256, salt, 1000000, dklen=32)
        else:
            key = sha256(password.encode("utf-8")).digest()
        assert len(key) == 32
        return mygram.aes256_set_encryption_key(key)

    def store_password(self, key: str, eK: list[int]):
        if key in self.pw_base:
            return
        with open(self.path, "ab") as file:
            pickle.dump((key, eK), file, protocol=4)
        self.pw_base[key] = eK

    def load_passwords(self):
        try:
            with open(self.path, "rb") as file:
                while True:
                    key, eK = pickle.load(file)
                    self.pw_base[key] = eK
        except (EOFError, FileNotFoundError): pass

    def check_password(self, key: str, name: str|None = None):
        try: return True, self.pw_base[key]
        except KeyError: pass

        password = input(f"Enter password for {name or key!r}: ")
        eK = self.password_to_ek(password)
        return False, eK

    def store(self, obj: Any, password: str|None, path: str, name: str|None = None):
        key = os.path.abspath(path)
        if password is None:
            _, eK = self.check_password(key, name)
        else:
            eK = self.password_to_ek(password)

        data = pickle.dumps(obj, protocol=4)
        pad = 16 - len(data) & 15

        data += bytes((pad,)) * pad
        iv = bytes(randint(1, 255) for i in range(16))

        encoded = mygram.cbc256(data, eK, iv, True, is_eK = True)
        if self.force:
            salt = self.salt
            assert isinstance(salt, bytes) and len(salt) == 32
        with open(path, "wb") as file:
            file.write(iv)
            if self.force: file.write(salt)
            file.write(encoded)

        self.store_password(key, eK)

    def load(self, path: str, name: str|None = None) -> Any:
        try:
            with open(path, "rb") as file:
                iv = file.read(16)
                if self.force: self.salt = file.read(32)
                encoded = file.read()
        except FileNotFoundError:
            return

        while True:
            key = os.path.abspath(path)
            stored, eK = self.check_password(key, name)
            eK2 = mygram.aes256_set_decryption_key(eK, is_eK = True)

            decoded = mygram.cbc256(encoded, eK2, iv, False, is_eK = True)

            try:
              # result = pickle.loads(decoded[:-decoded[-1]])
                result = pickle.loads(decoded)  # removing the pad can be skipped due to pickle's behaviour
                break
            except Exception:
                msg = f"Wrong password for {name or key!r}!"
                if stored:
                    raise ValueError(msg)
                print(msg)

        self.store_password(key, eK)
        return result

    def to_force(self, path: str, name: str|None = None):
        assert not self.force, "Storage is already in forced password mode!"

        data = self.load(path, name)
        assert data is not None
        # print(data)

        key = os.path.abspath(path)
        self.pw_base.pop(key)
        self.force = True

        self.store(data, None, path, name)
        print("Now you can switch force to True in the Storage constructor!")
        exit()


def test2():
    storage = Storage("test.asd")
    # storage.store({123: "meow!"}, "Meow!", "token.asd")
    obj = storage.load("token.asd", "token")
    print(obj)

if __name__ == "__main__":
    # test()
    test2()
