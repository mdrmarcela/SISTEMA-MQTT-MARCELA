# Sistema Publish/Subscribe Seguro - Redes II

Este projeto implementa um sistema de comunicação Publish/Subscribe semelhante ao MQTT, utilizando comunicação via TCP entre clientes e broker.

O sistema permite:

* criação de tópicos;
* inscrição de clientes em tópicos;
* saída de clientes de tópicos;
* publicação de mensagens em tópicos;
* entrega de mensagens para clientes inscritos;
* buffer de mensagens pendentes para clientes desconectados;
* autenticação do broker por certificado digital;
* autenticação de clientes por certificado digital e assinatura;
* criptografia do fluxo cliente-broker por envelopamento digital próprio;
* criptografia ponta a ponta do payload das mensagens.

## Tecnologias utilizadas

* Python
* Socket TCP
* Threads
* JSON
* Streamlit
* Cryptography

## Observação importante sobre segurança

O projeto não utiliza TLS/SSL.

A comunicação segura foi implementada sobre TCP puro por meio de um envelopamento digital próprio. O cliente valida o certificado digital do broker, gera uma chave de sessão simétrica e envia essa chave criptografada com a chave pública do broker.

Após o handshake, os pacotes trocados entre cliente e broker são criptografados com AES-GCM.

Além disso, o conteúdo das mensagens publicadas nos tópicos possui criptografia ponta a ponta. Dessa forma, o broker consegue ler apenas o cabeçalho necessário para encaminhamento, como tópico e remetente, mas não consegue decodificar o payload da mensagem.

## Estrutura do projeto

```text
SISTEMA-MQTT-MARCELA/
│
├── broker.py
├── client.py
├── main.py
│
├── certs/
│   ├── ca_clientes.crt
│   ├── ca_professor.crt
│   ├── clientes_autorizados.json
│   ├── chaves_topicos.json
│   │
│   ├── servidor/
│   │   ├── servidor.crt
│   │   ├── servidor.csr
│   │   └── servidor.key
│   │
│   └── clientes/
│       ├── cliente1/
│       │   ├── cliente1.crt
│       │   ├── cliente1.csr
│       │   └── cliente1.key
│       │
│       └── cliente2/
│           ├── cliente2.crt
│           ├── cliente2.csr
│           └── cliente2.key
│
└── utils/
    ├── __init__.py
    └── crypto_utils.py
```

## Instalação das dependências

Execute:

```bash
pip install streamlit streamlit-autorefresh cryptography
```

## Como executar

Primeiro, inicie o broker:

```bash
python broker.py
```

Depois, em outro terminal, inicie a interface do cliente:

```bash
streamlit run main.py
```

Na tela do Streamlit, conecte usando o nome do cliente correspondente à pasta do certificado.

Exemplos:

```text
cliente1
cliente2
```

## Funcionamento dos certificados

O broker possui um certificado digital em:

```text
certs/servidor/servidor.crt
```

e sua chave privada em:

```text
certs/servidor/servidor.key
```

A chave privada não deve ser compartilhada.

O arquivo:

```text
certs/ca_professor.crt
```

é utilizado pelo cliente para validar se o certificado do broker foi assinado pela Autoridade Certificadora da disciplina.

O arquivo:

```text
certs/ca_clientes.crt
```

é utilizado pelo broker para verificar se os certificados dos clientes foram assinados por uma autoridade confiável.

O arquivo:

```text
certs/clientes_autorizados.json
```

contém os fingerprints SHA-256 dos certificados dos clientes autorizados.

Exemplo:

```json
{
    "cliente1": "fingerprint_do_cliente1",
    "cliente2": "fingerprint_do_cliente2"
}
```

## Fluxo de autenticação

O processo de autenticação ocorre da seguinte forma:

1. O cliente se conecta ao broker usando TCP.
2. O broker envia seu certificado digital.
3. O cliente valida se o certificado do broker foi assinado pela CA do professor.
4. O cliente gera uma chave de sessão AES.
5. O cliente criptografa essa chave com a chave pública do broker.
6. O cliente envia seu certificado digital e assina um desafio enviado pelo broker.
7. O broker valida o certificado do cliente.
8. O broker verifica se o fingerprint do certificado está autorizado.
9. O broker verifica a assinatura do desafio.
10. Após a autenticação, os pacotes passam a ser enviados criptografados.

## Criptografia ponta a ponta

A criptografia ponta a ponta é aplicada ao conteúdo das mensagens.

Quando um cliente cria um tópico, ele gera uma chave E2E local para esse tópico. Essa chave deve ser compartilhada apenas com clientes autorizados.

O broker recebe apenas o payload criptografado e não possui a chave necessária para descriptografar a mensagem.

Exemplo do que o broker consegue ver:

```text
Tópico: redes
Remetente: cliente1
Payload: criptografado
```

O broker não consegue ver o texto original enviado pelo cliente.

## Testes realizados

### Teste 1: criação de tópico

O cliente cria um tópico e é inscrito automaticamente nele.

### Teste 2: inscrição em tópico

Outro cliente consegue visualizar o tópico existente e solicitar inscrição.

### Teste 3: publicação de mensagem

Um cliente inscrito consegue publicar uma mensagem no tópico.

### Teste 4: bloqueio de publicação sem inscrição

Um cliente não inscrito não consegue publicar mensagens em um tópico.

### Teste 5: confidencialidade no broker

Ao publicar uma mensagem, o broker não exibe o conteúdo original da mensagem, apenas informa que recebeu um payload criptografado.

### Teste 6: confidencialidade ponta a ponta

Um cliente sem a chave E2E do tópico não consegue ler o conteúdo da mensagem.

### Teste 7: entrega de mensagens pendentes

Se um cliente inscrito estiver desconectado no momento da publicação, a mensagem é armazenada no buffer do broker e entregue quando o cliente se reconecta.

## Observações finais

O sistema atende aos requisitos de comunicação via TCP, autenticação por certificados digitais, autorização de clientes, criptografia do fluxo de comunicação e confidencialidade ponta a ponta do payload das mensagens.

As chaves privadas dos clientes e do broker não devem ser compartilhadas.
