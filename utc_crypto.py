# Crypto module for encrypting and decrypting frame bodies.

import hashlib
import sys
import os

NONCE_SIZE = 12

class Crypto:
    # Crypto class encapsulates encryption and decryption logic using ChaCha20-Poly1305.
    def __init__(self):
        self.key = None
        self.nonce_prev = None
        self.Cipher = self.ensure_crypto_available()
        if self.Cipher is None:
            raise RuntimeError("Failed to initialize cipher. Ensure cryptography library is installed.")
            sys.exit(1)
        else:
            print("[crypto] ChaCha20-Poly1305 cipher initialized successfully.")

    def ensure_crypto_available(self):
        """
        Ensure the cryptography library is installed and usable.
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
            return ChaCha20Poly1305
        except ImportError as exc:
            raise RuntimeError(
                "cryptography library is required for ChaCha20-Poly1305 encryption. "
                "Install it with 'pip install cryptography'."
            ) from exc
            return None


    def derive_key_from_password(self, password):
        """
        Derive a 256-bit key from the password using SHA-256.
        """
        self.key = hashlib.sha256(password.encode("utf-8")).digest()
        return self.key


    def encrypt_frame_body(self, body):
        """
        Encrypt a frame body using ChaCha20-Poly1305.

        Args:
            body: Plaintext bytes to encrypt

        Returns:
            Nonce + ciphertext+tag bytes
        """
        ChaCha20Poly1305 = self.Cipher
        nonce = os.urandom(NONCE_SIZE)
        cipher = ChaCha20Poly1305(self.key)
        ciphertext = cipher.encrypt(nonce, body, None)
        return nonce + ciphertext


    def decrypt_frame_body(self, frame_body):
        """
        Decrypt a frame body produced by encrypt_frame_body.

        Args:
            frame_body: Nonce + ciphertext+tag bytes

        Returns:
            Plaintext bytes
        """
        if len(frame_body) < NONCE_SIZE:
            raise ValueError("[crypto] Encrypted frame body is too short")

        ChaCha20Poly1305 = self.Cipher
        nonce = frame_body[:NONCE_SIZE]
        if nonce == self.nonce_prev:
            # Nonce reuse detected, which suggests relay attack.
            raise ValueError("[crypto] Nonce reuse detected - possible replay attack")

        self.nonce_prev = nonce
        ciphertext = frame_body[NONCE_SIZE:]
        cipher = ChaCha20Poly1305(self.key)

        try:
            return cipher.decrypt(nonce, ciphertext, None)
        except Exception as exc:
            raise ValueError("[crypto] Decryption failed") from exc

if __name__ == "__main__":
    # Example usage
    print("0. Testing Crypto module...")
    crypto = Crypto()
    password = "my_secure_password"
    crypto.derive_key_from_password(password)

    plaintext = b"Hello"
    encrypted = crypto.encrypt_frame_body(plaintext)
    print(f"Encrypted: {encrypted.hex()}")

    nonce = encrypted[:NONCE_SIZE]
    ciphertext = encrypted[NONCE_SIZE:]
    print(f"Nonce: {nonce.hex()}")
    print(f"Ciphertext: {ciphertext.hex()}")

    decrypted = crypto.decrypt_frame_body(encrypted)
    print(f"Decrypted: {decrypted.decode('utf-8')}")

    # 1. Test wrong password
    print()
    print("1. Testing decryption with wrong password...")
    wrong_crypto = Crypto()
    wrong_crypto.derive_key_from_password("wrong_password")
    try:
        wrong_crypto.decrypt_frame_body(encrypted)
    except ValueError as exc:
        print(exc)
    
    # 2. Test nonce reuse
    print()
    print("2. Testing nonce reuse...")
    try:
        crypto.decrypt_frame_body(encrypted)  # Reusing the same encrypted data
    except ValueError as exc:
        print(exc)

    # 3. Test nonce created by attacker (simulate by modifying nonce)
    print()
    print("3. Testing decryption with attacker-created nonce...")
    attacker_nonce = os.urandom(NONCE_SIZE)
    attacker_encrypted = attacker_nonce + ciphertext
    print(f"Encrypted with attacker nonce: {attacker_encrypted.hex()}")
    print(f"Attacker Nonce: {attacker_nonce.hex()}")
    print(f"Attacker Ciphertext: {ciphertext.hex()}")
    try:
        crypto.decrypt_frame_body(attacker_encrypted)
    except ValueError as exc:
        print(exc)