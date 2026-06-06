# Sistema Publish/Subscribe com Broker

Este projeto implementa uma infraestrutura de comunicação composta por um **broker** e clientes, funcionando de forma semelhante ao protocolo **MQTT**, utilizando o modelo **publish/subscribe**.

---

## Parte 1 — Comunicação Básica

O sistema permite as seguintes funcionalidades:

- Criação de tópicos
- Inscrição de clientes em tópicos
- Publicação de mensagens em tópicos
- Recebimento de mensagens pelos clientes inscritos

### Broker

O notebook será utilizado como broker. Para iniciá-lo, execute no terminal:

```bash
python broker.py
```

### Cliente

No arquivo `client.py`, configure o IP do notebook que está rodando o broker:

```python
BROKER_HOST = "192.168.1.50"
BROKER_PORT = 1883
```

Instale as dependências necessárias:

```bash
pip install streamlit streamlit-autorefresh
```

Execute a interface do cliente:

```bash
streamlit run app.py
```

> **Observação:** o computador cliente precisa estar conectado à **mesma rede** que o notebook broker.

---

## Parte 2 — Autenticação e Bufferização

### O que foi adicionado

**Autenticação mTLS (mútua):**
- Ao se conectar, o cliente precisa apresentar um certificado X.509
- O certificado do cliente deve ter sido assinado pelo servidor (processo offline)
- O broker verifica a assinatura e confere se o CN do certificado bate com o nome informado pelo cliente

**Bufferização de mensagens:**
- Mensagens publicadas em um tópico ficam armazenadas no broker até que todos os clientes inscritos naquele tópico as recebam
- Ao reconectar, o cliente solicita explicitamente o download de todas as mensagens pendentes dos tópicos em que está inscrito

---

### Estrutura de certificados

```
certs/
├── servidor/
│   ├── servidor.crt   ← certificado do servidor (age como CA)
│   ├── servidor.key   ← chave privada do servidor
│   └── servidor.srl   ← controle de seriais das assinaturas
└── clientes/
    ├── cliente1/
    │   ├── cliente1.crt
    │   ├── cliente1.csr
    │   └── cliente1.key
    ├── cliente2/
    │   ├── cliente2.crt
    │   ├── cliente2.csr
    │   └── cliente2.key
    └── cliente3/
        ├── cliente3.crt
        ├── cliente3.csr
        └── cliente3.key
```

---

### Roteiro — Criar e assinar certificado de um novo cliente

> Todos os comandos devem ser executados no **Git Bash**, dentro da pasta do projeto.

#### 1. Abrir o Git Bash na pasta do projeto

Clique com o botão direito na pasta do projeto e selecione **Git Bash Here**.

#### 2. Criar a pasta do cliente

```bash
mkdir -p certs/clientes/cliente3
```

#### 3. Gerar o par de chaves do cliente

```bash
openssl genrsa -out certs/clientes/cliente3/cliente3.key 2048
```

#### 4. Gerar o CSR (pedido de assinatura)

O cliente gera um CSR com seus dados e envia ao servidor para ser assinado:

```bash
openssl req -new \
  -key certs/clientes/cliente3/cliente3.key \
  -out certs/clientes/cliente3/cliente3.csr \
  -subj "/C=BR/ST=SC/L=Lages/O=RedesII/CN=cliente3"
```

#### 5. Servidor assina o certificado do cliente

O servidor usa sua chave privada para assinar o certificado do cliente:

```bash
openssl x509 -req \
  -in certs/clientes/cliente3/cliente3.csr \
  -CA certs/servidor/servidor.crt \
  -CAkey certs/servidor/servidor.key \
  -CAserial certs/servidor/servidor.srl \
  -out certs/clientes/cliente3/cliente3.crt \
  -days 365
```

> **Importante:** usa `-CAserial` (não `-CAcreateserial`) para aproveitar o arquivo `.srl` já existente, mantendo a sequência de seriais.

#### 6. Verificar se foi assinado corretamente

```bash
openssl verify -CAfile certs/servidor/servidor.crt certs/clientes/cliente3/cliente3.crt
```

Resultado esperado:

```
certs/clientes/cliente3/cliente3.crt: OK
```

#### 7. Confirmar Issuer e Subject

```bash
openssl x509 -in certs/clientes/cliente3/cliente3.crt -text -noout | grep -E "Issuer|Subject|CA"
```

Resultado esperado:

```
Issuer: CN=ServidorBroker   ← assinado pelo servidor
Subject: CN=cliente3        ← identidade do cliente
CA:FALSE                    ← cliente não é CA
```

#### 8. Conectar como cliente3

Suba o broker e o cliente normalmente e, na tela de login, digite `cliente3`.

---

### Como rodar a Parte 2

#### Broker (notebook)

```bash
python broker.py
```

#### Cliente (cada computador)

```bash
streamlit run app.py
```

Na tela de login, digite o nome do cliente (`cliente1`, `cliente2` ou `cliente3`) — o sistema buscará automaticamente o certificado correspondente em `certs/clientes/<nome>/`.

> **Observação:** todos os computadores precisam ter a pasta `certs/` com os certificados corretos e estar na mesma rede que o broker.