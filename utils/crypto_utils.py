
import json
import base64
import secrets

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidSignature

# ============================================================
# Funções auxiliares de Base64
# ============================================================

def b64_encode(dados: bytes) -> str:
    """
    Converte bytes para texto Base64.

    Isso é necessário porque dados criptográficos, como chaves e 
    assinaturas  são bytes. Como o sistema troca mensagen
    em JSON, precisamos transformar esses bytes em texto.
    """
    return base64.b64encode(dados).decode("utf-8")


def b64_decode(texto: str) -> bytes:
    """
    Converte texto Base64 de volta para bytes.
    """
    return base64.b64decode(texto.encode("utf-8"))


# ============================================================
# Leitura de certificados e chaves em formato PEM
# ============================================================

def carregar_certificado(caminho_certificado: str):
    """
    Lê um certificado digital de um arquivo .crt/

    Retorna um objeto certificado que pode ser usado para:
    - verificar assinatura;
    - obter chave pública;
    - obter CN;
    - calcular fingerprint.
    """
    with open(caminho_certificado, "rb") as arquivo:
        dados = arquivo.read()

    return x509.load_pem_x509_certificate(dados)


def carregar_chave_privada(caminho_chave: str):
    """
    Lê uma chave privada de um arquivo .key.

    Essa função é usada pelo broker para carregar sua chave privada
    e pelo cliente para carregar sua chave privada.
    """
    with open(caminho_chave, "rb") as arquivo:
        dados = arquivo.read()

    return serialization.load_pem_private_key(
        dados,
        password=None
    )


def certificado_para_pem(caminho_certificado: str) -> str:
    """
    Lê um certificado e retorna seu conteúdo em texto PEM.

    Essa função é usada quando precisamos enviar um certificado
    dentro de um pacote JSON.
    """
    with open(caminho_certificado, "r", encoding="utf-8") as arquivo:
        return arquivo.read()


def carregar_certificado_pem_texto(texto_pem: str):
    """
    Recebe um certificado em formato texto PEM e transforma
    em objeto certificado.

    Isso é usado quando o certificado chega pela rede dentro de um JSON.
    """
    return x509.load_pem_x509_certificate(
        texto_pem.encode("utf-8")
    )


# ============================================================
# Validação de certificados
# ============================================================

def verificar_assinatura_certificado(certificado, certificado_ca) -> bool:
    """
    Verifica se um certificado foi assinado pela CA.

    No projeto, isso é usado em dois momentos:

    1. Cliente validando o certificado do broker:
       O cliente verifica se o certificado do broker foi assinado
       pela CA do professor.

    2. Broker validando o certificado do cliente:
       O broker verifica se o certificado do cliente foi assinado
       por mim.
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
    Obtém o Common Name, de um certificado.

    O CN é usado apenas para identificação.
    A autenticação real não depende somente dele.
    """
    try:
        atributos = certificado.subject.get_attributes_for_oid(
            NameOID.COMMON_NAME
        )

        if atributos:
            return atributos[0].value

        return None

    except Exception:
        return None


def obter_fingerprint_sha256(certificado) -> str:
    """
    Gera o fingerprint SHA-256 do certificado.

    O fingerprint funciona como uma impressão digital do certificado.
    Ele é usado para garantir que o certificado apresentado é exatamente
    o certificado autorizado.
    """
    fingerprint = certificado.fingerprint(hashes.SHA256())
    return fingerprint.hex()

# ============================================================
# RSA: criptografia assimétrica e assinatura digital
# ============================================================

def criptografar_com_chave_publica(chave_publica, dados: bytes) -> bytes:
    """
    Criptografa dados usando a chave pública RSA.

    No projeto, essa função é usada no handshake:
    o cliente criptografa a chave de sessão AES usando a chave pública
    do broker.

    Assim, somente o broker consegue descriptografar, pois apenas ele
    possui a chave privada correspondente.
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

    No projeto, o broker usa essa função para descriptografar
    a chave de sessão AES enviada pelo cliente.
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

    No projeto, o cliente assina os dados do handshake para provar
    que possui a chave privada correspondente ao seu certificado.
    """
    return chave_privada.sign(
        dados,
        padding.PKCS1v15(),
        hashes.SHA256()
    )


def verificar_assinatura_dados(chave_publica, assinatura: bytes, dados: bytes) -> bool:
    """
    Verifica uma assinatura digital.

    O broker usa essa função para verificar se a assinatura enviada
    pelo cliente foi realmente feita com a chave privada dele.
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
# AES-GCM para envelopamento digital próprio
# ============================================================

def gerar_chave_sessao() -> bytes:
    """
    Gera uma chave AES de 256 bits.

    Essa chave é usada para criptografar a comunicação entre
    cliente e broker depois do handshake.
    """
    return AESGCM.generate_key(bit_length=256)


def criptografar_json(chave: bytes, pacote: dict) -> dict:
    """
    Criptografa um pacote JSON usando AES-GCM.

    Essa função é usada no envelopamento digital próprio.
    Ela protege os pacotes trocados entre cliente e broker.

    Retorna um envelope com:
    - nonce: valor aleatório necessário para o AES-GCM;
    - dados: pacote criptografado.
    """
    aesgcm = AESGCM(chave)

    # Nonce aleatório de 12 bytes, tamanho recomendado para AES-GCM.
    nonce = secrets.token_bytes(12)

    # Converte o dicionário Python para JSON em bytes.
    dados_json = json.dumps(
        pacote,
        ensure_ascii=False
    ).encode("utf-8")

    # Criptografa os dados.
    dados_criptografados = aesgcm.encrypt(
        nonce,
        dados_json,
        None
    )

    # Como nonce e dados criptografados são bytes, convertemos para Base64.
    return {
        "nonce": b64_encode(nonce),
        "dados": b64_encode(dados_criptografados)
    }


def descriptografar_json(chave: bytes, envelope: dict) -> dict:
    """
    Descriptografa um envelope AES-GCM e retorna o pacote JSON original.
    """
    aesgcm = AESGCM(chave)

    # Converte os campos Base64 de volta para bytes.
    nonce = b64_decode(envelope["nonce"])
    dados_criptografados = b64_decode(envelope["dados"])

    # Descriptografa os dados.
    dados_json = aesgcm.decrypt(
        nonce,
        dados_criptografados,
        None
    )

    # Converte o JSON de volta para dicionário Python.
    return json.loads(dados_json.decode("utf-8"))


# ============================================================
# Criptografia ponta a ponta por tópico
# ============================================================

def gerar_chave_topico() -> str:
    """
    Gera uma chave AES de 256 bits para um tópico.

    Essa chave é usada para criptografia ponta a ponta.
    Ela deve ficar apenas com os clientes autorizados do tópico.

    O broker não recebe essa chave.
    """
    chave = AESGCM.generate_key(bit_length=256)
    return b64_encode(chave)


def criptografar_payload_ponta_a_ponta(chave_topico_b64: str, mensagem: str) -> dict:
    """
    Criptografa somente o payload da mensagem.

    O broker consegue ver o cabeçalho, como:
    - tópico;
    - remetente;
    - tipo do pacote.

    Mas não consegue ler o conteúdo da mensagem, pois o payload
    está criptografado com a chave E2E do tópico.
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

    Essa função é usada apenas pelos clientes que possuem a chave E2E
    do tópico.
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