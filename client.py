import socket
import threading
import json
from datetime import datetime
import os
from utils.crypto_utils import (
    verificar_certificado, gerar_par_chaves, carregar_certificado_broker,
    descriptografar_aes, descriptografar_ec, carregar_chave_privada_pem,
    load_ca_cert
)
from utils.pubsub_utils import enviar_sub, enviar_pub 
from cryptography import x509
from cryptography.hazmat.backends import default_backend
import base64

BROKER_HOST = 'localhost'
BROKER_PORT = 1883
CA_CERT_PATH = 'certs/ca_cert.cer'

class ClienteWeb:
    def enviar_sub(self, topico):
        enviar_sub(self, topico)

    def enviar_pub(self, topico, mensagem):
       enviar_pub(self, topico, mensagem)
        
    def __init__(self):
        self.socket = None
        self.mensagens = []
        self.conectado = False
        self.nome_cliente = ""
        self.pub_key_path = ""
        self.priv_key_path = ""
        self.subscricoes = []

    def receber_mensagens(self):
        while self.conectado:
            try:
                data = self.socket.recv(4096)
                if not data:
                    print(f"[DEBUG] Conexão com broker encerrada para {self.nome_cliente}")
                    break
                pacote = json.loads(data.decode())
                if pacote.get("tipo") == "mensagem":
                    topico = pacote.get("topico")
                    mensagem = pacote.get("mensagem")
                    destinatario = pacote.get("destinatario")
                    if destinatario != self.nome_cliente:
                        print(f"[DEBUG] Ignorando mensagem para {destinatario}, cliente atual: {self.nome_cliente}")
                        continue
                    chave_aes_cript = mensagem["aes"]
                    msg_criptografada = bytes.fromhex(mensagem["msg"])
                    ephemeral_public_key_pem = mensagem["ephemeral_public_key"]
                    private_key = carregar_chave_privada_pem(self.priv_key_path, senha=None)
                    chave_aes = descriptografar_ec(chave_aes_cript, ephemeral_public_key_pem, private_key)
                    mensagem_clara = descriptografar_aes(msg_criptografada, chave_aes)
                    remetente = pacote.get("id", "Desconhecido")
                    hora = datetime.now().strftime("%H:%M")
                    mensagem_formatada = f"{remetente}: {mensagem_clara} [{hora}]"
                    self.mensagens.append(f"[{topico}] {mensagem_formatada}")
                    print(f"[DEBUG] Mensagem recebida no tópico {topico} de {remetente}: {mensagem_clara}")

            except Exception as e:
                print(f"[ERRO] Falha ao receber mensagem: {e}")
                break

    def conectar(self, nome_cliente):
        try:
            self.nome_cliente = nome_cliente
            # Gera par de chaves e salva os caminhos
            self.pub_key_path, self.priv_key_path = gerar_par_chaves(nome_cliente)
            # Conexão com o broker
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.connect((BROKER_HOST, BROKER_PORT))
            # Receber certificado do broker
            broker_cert_base64 = b""
            while True:
                chunk = self.socket.recv(2048)
                broker_cert_base64 += chunk
                if len(chunk) < 2048:
                    break
            cert_bytes = base64.b64decode(broker_cert_base64)
            cert_obj = x509.load_pem_x509_certificate(cert_bytes, default_backend())
            ca_cert_obj = load_ca_cert(CA_CERT_PATH)
            if not verificar_certificado(cert_obj, ca_cert_obj):
                return False, "Certificado do broker inválido."
            # Enviar ID + chave pública
            with open(self.pub_key_path, 'rb') as f:
                chave_pub_pem = f.read().decode()
            pacote_auth = json.dumps({
                "tipo": "autenticacao",
                "id": self.nome_cliente,
                "chave_publica": chave_pub_pem
            })
            self.socket.send(pacote_auth.encode())
            # Aguardar resposta
            resposta = self.socket.recv(1024).decode()
            if resposta.strip() != "AUTENTICADO":
                return False, "Broker recusou a autenticação."
            self.conectado = True
            threading.Thread(target=self.receber_mensagens, daemon=True).start()
            print(f"[✓] Cliente {self.nome_cliente} conectado e autenticado")
            return True, "Conectado e autenticado com sucesso."
        except Exception as e:
            print(f"[ERRO] Erro na conexão para {self.nome_cliente}: {e}")
            return False, f"Erro na conexão: {e}"