# SISTEMA PUBLISH/SUBSCRIBE

Este projeto consiste em uma infraestrutura de comunicação composta por um **broker** e um **cliente**, funcionando de forma semelhante ao protocolo **MQTT**, utilizando o modelo **publish/subscribe**.

## Parte 1

Nesta etapa inicial, o sistema deve permitir as seguintes funcionalidades:

* Criação de tópicos;
* Inscrição de clientes em tópicos;
* Publicação de mensagens;
* Recebimento de mensagens pelos clientes inscritos.

---

## Broker

O meu notebook será utilizado como **broker**.

Para iniciar o broker, execute o seguinte comando no terminal:

```bash
python broker.py
```

---

## Cliente 1 — Computador 1

No arquivo `cliente.py`, configure o IP do notebook que está rodando o broker:

```python
BROKER_HOST = "192.168.1.50"
BROKER_PORT = 1883
```

Depois, instale as dependências necessárias:

```bash
pip install streamlit
```

```bash
pip install streamlit-autorefresh
```

Em seguida, execute a interface do cliente com o comando:

```bash
streamlit run main.py
```

---

## Observação

O computador cliente precisa estar conectado à mesma rede que o notebook broker para conseguir se comunicar com ele.


---
## Na parte do projeto, com o botão direito, abra o git push here

mkdir -p certs/clientes/cliente3

1. Criar a pasta do cliente3
bashmkdir -p certs/clientes/cliente3
2. Gerar o par de chaves do cliente3
bashopenssl genrsa -out certs/clientes/cliente3/cliente3.key 2048
3. Gerar o CSR (pedido de assinatura)
bashopenssl req -new \
  -key certs/clientes/cliente3/cliente3.key \
  -out certs/clientes/cliente3/cliente3.csr \
  -subj "/C=BR/ST=SC/L=Lages/O=RedesII/CN=cliente3"
4. Servidor assina o certificado do cliente3
bashopenssl x509 -req \
  -in certs/clientes/cliente3/cliente3.csr \
  -CA certs/servidor/servidor.crt \
  -CAkey certs/servidor/servidor.key \
  -CAserial certs/servidor/servidor.srl \
  -out certs/clientes/cliente3/cliente3.crt \
  -days 365

Importante: usa -CAserial (não -CAcreateserial) para aproveitar o arquivo .srl que já existe, mantendo a sequência de seriais.

5. Verificar se foi assinado corretamente
bashopenssl verify -CAfile certs/servidor/servidor.crt certs/clientes/cliente3/cliente3.crt
Deve aparecer:
certs/clientes/cliente3/cliente3.crt: OK
6. Confirmar o Issuer e Subject
bashopenssl x509 -in certs/clientes/cliente3/cliente3.crt -text -noout | grep -E "Issuer|Subject|CA"
Deve aparecer:
Issuer: CN=ServidorBroker
Subject: CN=cliente3
CA:FALSE
7. Subir o sistema e conectar como cliente3
No terminal do VS Code:
bashstreamlit run app.py
No navegador, digita cliente3 e conecta.

Esse roteiro mostra claramente para o professor que:

O cliente gerou suas próprias chaves e o CSR
O servidor assinou offline
O sistema aceita o novo cliente sem nenhuma alteração no código


