from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.exceptions import InvalidSignature


def carregar_certificado(caminho):
    with open(caminho, "rb") as arquivo:
        return x509.load_pem_x509_certificate(arquivo.read())


servidor = carregar_certificado("certs/servidor/servidor.crt")
ca_professor = carregar_certificado("certs/ca_professor.crt")

print("=== CERTIFICADO DO SERVIDOR ===")
print("Subject:", servidor.subject.rfc4514_string())
print("Issuer :", servidor.issuer.rfc4514_string())

print("\n=== CA DO PROFESSOR ===")
print("Subject:", ca_professor.subject.rfc4514_string())
print("Issuer :", ca_professor.issuer.rfc4514_string())

print("\n=== VERIFICAÇÃO ===")

try:
    ca_professor.public_key().verify(
        servidor.signature,
        servidor.tbs_certificate_bytes,
        padding.PKCS1v15(),
        servidor.signature_hash_algorithm
    )

    print("OK: o certificado do servidor foi assinado por essa CA.")

except InvalidSignature:
    print("ERRO: essa CA NÃO assinou o certificado do servidor.")

except Exception as e:
    print("ERRO ao verificar:", e)