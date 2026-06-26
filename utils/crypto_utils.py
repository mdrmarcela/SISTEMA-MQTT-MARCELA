import os
import json
import base64
import secrets

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidSignature


# ============================================================
# Funções auxiliares de Base64
# ============================================================

def b64_encode(dados: bytes) -> str:
    return base64.b64encode(dados).decode("utf-8")


def b64_decode(texto: str) -> bytes:
    return base64.b64decode(texto.encode("utf-8"))


# ============================================================
# Leitura de arquivos PEM
# ============================================================

def carregar_certificado(caminho_certificado: str):
    with open(caminho_certificado, "rb") as arquivo:
        dados = arquivo.read()

    return x509.load_pem_x509_certificate(dados)


def carregar_chave_privada(caminho_chave: str):
    with open(caminho_chave, "rb") as arquivo:
        dados = arquivo.read()

    return serialization.load_pem_private_key(
        dados,
        password=None
    )


def certificado_para_pem(caminho_certificado: str) -> str:
    with open(caminho_certificado, "r", encoding="utf-8") as arquivo:
        return arquivo.read()


def carregar_certificado_pem_texto(texto_pem: str):
    return x509.load_pem_x509_certificate(
        texto_pem.encode("utf-8")
    )


# ============================================================
# Validação de certificado
# ============================================================

def verificar_assinatura_certificado(certificado, certificado_ca) -> bool:
    """
    Verifica se o certificado foi assinado pela CA informada.

    Usado para:
    - cliente validar o certificado do broker;
    - broker validar certificado do cliente.
    """
    chave_publica_ca = certificado_ca.public_key()

    try:
        chave_publica_ca.verify(
            certificado.signature,
            certificado.tbs_certificate_bytes,
            padding.PKCS1v15(),
            certificado.signature_hash_algorithm
        )
        return True

    except InvalidSignature:
        return False

    except Exception:
        return False


def obter_common_name_certificado(certificado):
    """
    Pega o CN apenas para identificação/log.
    Não deve ser a única validação.
    """
    try:
        atributos = certificado.subject.get_attributes_for_oid(
            x509.NameOID.COMMON_NAME
        )

        if atributos:
            return atributos[0].value

        return None

    except Exception:
        return None


def obter_fingerprint_sha256(certificado) -> str:
    """
    Gera o fingerprint SHA-256 do certificado.
    """
    fingerprint = certificado.fingerprint(hashes.SHA256())
    return fingerprint.hex()


# ============================================================
# RSA
# ============================================================

def criptografar_com_chave_publica(chave_publica, dados: bytes) -> bytes:
    """
    Criptografa dados usando a chave pública RSA.
    Usado no handshake para proteger a chave de sessão.
    """
    return chave_publica.encrypt(
        dados,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )


def descriptografar_com_chave_privada(chave_privada, dados_criptografados: bytes) -> bytes:
    """
    Descriptografa dados usando a chave privada RSA.
    """
    return chave_privada.decrypt(
        dados_criptografados,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )


def assinar_dados(chave_privada, dados: bytes) -> bytes:
    """
    Assina dados usando a chave privada RSA.
    Usado para provar posse da chave privada do cliente.
    """
    return chave_privada.sign(
        dados,
        padding.PKCS1v15(),
        hashes.SHA256()
    )


def verificar_assinatura_dados(chave_publica, assinatura: bytes, dados: bytes) -> bool:
    """
    Verifica assinatura feita sobre dados.
    """
    try:
        chave_publica.verify(
            assinatura,
            dados,
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        return True

    except InvalidSignature:
        return False

    except Exception:
        return False


# ============================================================
# AES-GCM para envelopamento digital
# ============================================================

def gerar_chave_sessao() -> bytes:
    """
    Gera uma chave AES de 256 bits.
    """
    return AESGCM.generate_key(bit_length=256)


def criptografar_json(chave: bytes, pacote: dict) -> dict:
    """
    Criptografa um pacote JSON usando AES-GCM.
    Retorna um envelope contendo nonce e dados criptografados.
    """
    aesgcm = AESGCM(chave)
    nonce = secrets.token_bytes(12)

    dados_json = json.dumps(
        pacote,
        ensure_ascii=False
    ).encode("utf-8")

    dados_criptografados = aesgcm.encrypt(
        nonce,
        dados_json,
        None
    )

    return {
        "nonce": b64_encode(nonce),
        "dados": b64_encode(dados_criptografados)
    }


def descriptografar_json(chave: bytes, envelope: dict) -> dict:
    """
    Descriptografa um envelope AES-GCM e retorna o pacote JSON original.
    """
    aesgcm = AESGCM(chave)

    nonce = b64_decode(envelope["nonce"])
    dados_criptografados = b64_decode(envelope["dados"])

    dados_json = aesgcm.decrypt(
        nonce,
        dados_criptografados,
        None
    )

    return json.loads(dados_json.decode("utf-8"))


# ============================================================
# Chave por tópico para criptografia ponta a ponta
# ============================================================

def gerar_chave_topico() -> str:
    """
    Gera uma chave de tópico em Base64.
    Essa chave deve ser conhecida apenas pelos clientes inscritos.
    O broker não deve ter acesso a ela.
    """
    chave = AESGCM.generate_key(bit_length=256)
    return b64_encode(chave)


def criptografar_payload_ponta_a_ponta(chave_topico_b64: str, mensagem: str) -> dict:
    """
    Criptografa somente o payload da mensagem.
    O broker consegue ver o tópico, mas não consegue ler a mensagem.
    """
    chave = b64_decode(chave_topico_b64)
    aesgcm = AESGCM(chave)
    nonce = secrets.token_bytes(12)

    dados = mensagem.encode("utf-8")

    payload_criptografado = aesgcm.encrypt(
        nonce,
        dados,
        None
    )

    return {
        "nonce": b64_encode(nonce),
        "payload": b64_encode(payload_criptografado)
    }


def descriptografar_payload_ponta_a_ponta(chave_topico_b64: str, envelope_payload: dict) -> str:
    """
    Descriptografa o payload ponta a ponta.
    Essa função será usada apenas no cliente.
    """
    chave = b64_decode(chave_topico_b64)
    aesgcm = AESGCM(chave)

    nonce = b64_decode(envelope_payload["nonce"])
    payload_criptografado = b64_decode(envelope_payload["payload"])

    dados = aesgcm.decrypt(
        nonce,
        payload_criptografado,
        None
    )

    return dados.decode("utf-8")