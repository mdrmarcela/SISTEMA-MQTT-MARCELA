import socket
import threading
import json
import os
from utils.crypto_utils import (
    enviar_mensagem,
    carregar_certificado_broker,
    carregar_chave_publica_pem,
    gerar_chave_aes,
    criptografar_aes,
    criptografar_ec
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend

BROKER_HOST = 'localhost'
BROKER_PORT = 1883

clientes_conectados = {}  # id_cliente -> socket
subscricoes = {}          # topico -> lista de id_cliente

def tratar_cliente(conn, addr):
    id_cliente = None
    try:
        print(f"[+] Conexão de {addr}")
        cert_base64 = carregar_certificado_broker()
        conn.send(cert_base64.encode())
        dados_iniciais = conn.recv(8192).decode()
        pacote = json.loads(dados_iniciais)
        if pacote['tipo'] == 'autenticacao':
            id_cliente = pacote['id']
            chave_publica = pacote.get('chave_publica', '').strip()
            if not chave_publica:
                raise ValueError("Chave pública ausente no pacote de autenticação")
            chave_path = f"certs/pub_keys/{id_cliente}_pub.pem"
            try:
                with open(chave_path, "wb") as f:
                    chave_data = chave_publica.encode() if isinstance(chave_publica, str) else chave_publica
                    f.write(chave_data)
                with open(chave_path, "rb") as f:
                    key = serialization.load_pem_public_key(f.read(), default_backend())
                    print(f"[DEBUG] Chave pública de {id_cliente} carregada, tipo: {type(key)}, caminho: {chave_path}")
                    if not isinstance(key, ec.EllipticCurvePublicKey):
                        raise ValueError(f"Chave de {id_cliente} não é EC: {type(key)}")
                print(f"[✓] Cliente autenticado: {id_cliente}")
                clientes_conectados[id_cliente] = conn
                conn.send(b"AUTENTICADO")
            except Exception as e:
                print(f"[ERRO] Falha ao salvar ou validar chave pública de {id_cliente}: {e}")
                conn.close()
                return

        while True:
            dados = conn.recv(8192)
            if not dados:
                print(f"[DEBUG] Conexão com {id_cliente} encerrada: sem dados recebidos")
                break
            pacote = json.loads(dados.decode())
            tipo = pacote.get('tipo')
            id_cliente = pacote.get('id')

            if tipo == 'inscrever':
                topico = pacote['topico']
                if id_cliente not in subscricoes.setdefault(topico, []):
                    subscricoes[topico].append(id_cliente)
                    print(f"[+] {id_cliente} inscrito em {topico}")
                else:
                    print(f"[DEBUG] {id_cliente} já inscrito em {topico}")

            elif tipo == 'publicar':
                topico = pacote['topico']
                mensagem = pacote['mensagem']
                print(f"[DEBUG] Publicando no tópico {topico}, mensagem: {mensagem}")
                print(f"[DEBUG] Subscricoes para o tópico {topico}: {subscricoes.get(topico, [])}")
                for nome_destinatario in subscricoes.get(topico, []):
                    if nome_destinatario == id_cliente:
                        continue
                    caminho_chave = f"certs/pub_keys/{nome_destinatario}_pub.pem"
                    if not os.path.exists(caminho_chave):
                        print(f"[DEBUG] Chave pública não encontrada para {nome_destinatario} em {caminho_chave}")
                        continue
                    try:
                        chave_pub = carregar_chave_publica_pem(caminho_chave)
                        print(f"[DEBUG] Chave pública de {nome_destinatario} carregada, tipo: {type(chave_pub)}, caminho: {caminho_chave}")
                        if not isinstance(chave_pub, ec.EllipticCurvePublicKey):
                            raise ValueError(f"Chave de {nome_destinatario} não é EC: {type(chave_pub)}")
                        chave_aes = gerar_chave_aes()
                        msg_criptografada = criptografar_aes(mensagem, chave_aes)
                        chave_aes_cript, ephemeral_public_key = criptografar_ec(chave_aes, chave_pub)
                        pacote_pub = json.dumps({
                            "tipo": "mensagem",
                            "topico": topico,
                            "mensagem": {
                                "aes": chave_aes_cript.hex(),
                                "msg": msg_criptografada.hex(),
                                "ephemeral_public_key": ephemeral_public_key.public_bytes(
                                    encoding=serialization.Encoding.PEM,
                                    format=serialization.PublicFormat.SubjectPublicKeyInfo
                                ).decode()
                            },
                            "id": id_cliente,
                            "destinatario": nome_destinatario
                        })
                        if nome_destinatario in clientes_conectados:
                            try:
                                clientes_conectados[nome_destinatario].send(pacote_pub.encode())
                                print(f"[{topico}] {id_cliente} → {nome_destinatario}")
                            except socket.error as se:
                                print(f"[ERRO] Falha ao enviar mensagem para {nome_destinatario}: {se}")
                        else:
                            print(f"[DEBUG] Cliente {nome_destinatario} não está conectado")
                    except Exception as e:
                        print(f"[ERRO] Falha ao publicar para {nome_destinatario}: {e}")

    except Exception as e:
        print(f"[!] Erro com cliente {addr}: {e}")
    finally:
        if id_cliente and id_cliente in clientes_conectados:
            print(f"[DEBUG] Removendo cliente {id_cliente} da lista de conectados")
            del clientes_conectados[id_cliente]
            # Remover cliente de todas as subscrições
            for topico in subscricoes:
                if id_cliente in subscricoes[topico]:
                    subscricoes[topico].remove(id_cliente)
            print(f"[DEBUG] {id_cliente} removido das subscrições")
        conn.close()
        print(f"[DEBUG] Conexão com {addr} fechada")

def iniciar_broker():
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        servidor.bind((BROKER_HOST, BROKER_PORT))
        servidor.listen(5)
        print(f"[*] Broker ouvindo em {BROKER_HOST}:{BROKER_PORT}")
    except Exception as e:
        print(f"[ERRO] Falha ao iniciar o broker: {e}")
        return

    while True:
        try:
            conn, addr = servidor.accept()
            threading.Thread(target=tratar_cliente, args=(conn, addr)).start()
        except Exception as e:
            print(f"[ERRO] Falha ao aceitar conexão: {e}")

if __name__ == '__main__':
    iniciar_broker()