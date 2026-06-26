import streamlit as st
from client import ClienteWeb
from streamlit_autorefresh import st_autorefresh
from datetime import datetime

st.set_page_config(
    page_title="Redes Chat",
    layout="centered"
)

# ============================================================
# Estados da aplicação
# ============================================================

if "cliente" not in st.session_state:
    st.session_state.cliente = ClienteWeb()

if "topicos" not in st.session_state:
    st.session_state.topicos = []

if "topicos_inscritos" not in st.session_state:
    st.session_state.topicos_inscritos = []

if "mensagens_por_topico" not in st.session_state:
    st.session_state.mensagens_por_topico = {}


cliente = st.session_state.cliente

if not hasattr(cliente, "topicos_desinscritos"):
    cliente.topicos_desinscritos = []

# ============================================================
# Cabeçalho
# ============================================================

st.title("Redes Chat")
st.caption(
    "Publish/Subscribe com TCP, envelopamento digital próprio "
    "e criptografia ponta a ponta"
)

# ============================================================
# Tela de conexão
# ============================================================

if not cliente.conectado:
    st.subheader("Conectar ao broker")

    nome = st.text_input("Nome do cliente:")

    if st.button("Conectar"):
        if nome.strip():
            sucesso, mensagem = cliente.conectar(nome.strip())

            if sucesso:
                st.success(mensagem)

                try:
                    cliente.listar_topicos()
                except Exception:
                    pass

                st.rerun()
            else:
                st.error(mensagem)
        else:
            st.warning("Digite um nome válido.")

    st.info(
        "Use o mesmo nome da pasta do certificado. "
        "Exemplo: cliente1 ou cliente2."
    )

    st.stop()

# ============================================================
# Atualização automática
# ============================================================

st_autorefresh(interval=2000, key="atualizar_tela")

st.success(f"Conectado como: {cliente.nome_cliente}")

# ============================================================
# Atualiza lista de tópicos recebida do broker
# ============================================================

if cliente.topicos:
    st.session_state.topicos = cliente.topicos

# ============================================================
# Processa mensagens recebidas
# ============================================================

for msg in cliente.mensagens:
    if msg.startswith("[") and "]" in msg:
        partes = msg.split("]", 1)

        topico_msg = partes[0].replace("[", "").strip()
        conteudo = partes[1].strip()

        st.session_state.mensagens_por_topico.setdefault(
            topico_msg,
            []
        ).append(conteudo)

    else:
        st.session_state.mensagens_por_topico.setdefault(
            "Sistema",
            []
        ).append(msg)

cliente.mensagens.clear()

# ============================================================
# Processa tópicos desinscritos
# ============================================================

for topico in cliente.topicos_desinscritos:
    if topico in st.session_state.topicos_inscritos:
        st.session_state.topicos_inscritos.remove(topico)

cliente.topicos_desinscritos.clear()

# ============================================================
# Menu lateral
# ============================================================

topico_ativo = None

with st.sidebar:
    st.header("Tópicos")

    novo_topico = st.text_input("Novo tópico:")

    if st.button("Criar tópico"):
        if novo_topico.strip():
            topico = novo_topico.strip()

            sucesso, mensagem = cliente.criar_topico(topico)

            if sucesso:
                if topico not in st.session_state.topicos:
                    st.session_state.topicos.append(topico)

                if topico not in st.session_state.topicos_inscritos:
                    st.session_state.topicos_inscritos.append(topico)

                st.success(mensagem)
                st.rerun()
            else:
                st.error(mensagem)
        else:
            st.warning("Digite o nome do tópico.")

    if st.button("Atualizar tópicos"):
        cliente.listar_topicos()
        st.rerun()

    st.divider()

    if st.session_state.topicos:
        topico_ativo = st.selectbox(
            "Escolha um tópico:",
            st.session_state.topicos
        )

        inscrito = topico_ativo in st.session_state.topicos_inscritos

        if inscrito:
            st.success("Inscrito")

            if st.button("Sair do tópico"):
                sucesso, mensagem = cliente.desinscrever(topico_ativo)

                if sucesso:
                    st.rerun()
                else:
                    st.error(mensagem)

        else:
            st.warning("Não inscrito")

            if st.button("Inscrever"):
                sucesso, mensagem = cliente.inscrever(topico_ativo)

                if sucesso:
                    if topico_ativo not in st.session_state.topicos_inscritos:
                        st.session_state.topicos_inscritos.append(topico_ativo)

                    st.rerun()
                else:
                    st.error(mensagem)

    else:
        st.info("Nenhum tópico criado.")

    st.divider()

    st.header("Chave E2E")

    if topico_ativo:
        chave_atual = cliente.exportar_chave_topico(topico_ativo)

        if chave_atual:
            st.success("Este cliente possui a chave deste tópico.")

            with st.expander("Mostrar chave do tópico"):
                st.warning(
                    "Compartilhe esta chave somente com clientes autorizados."
                )
                st.code(chave_atual)

        else:
            st.warning("Este cliente não possui a chave E2E deste tópico.")

        with st.expander("Importar chave E2E"):
            chave_digitada = st.text_area(
                "Cole aqui a chave E2E do tópico:",
                height=100
            )

            if st.button("Salvar chave E2E"):
                sucesso, mensagem = cliente.importar_chave_topico(
                    topico_ativo,
                    chave_digitada.strip()
                )

                if sucesso:
                    st.success(mensagem)
                    st.rerun()
                else:
                    st.error(mensagem)

    else:
        st.info("Escolha um tópico para gerenciar a chave.")

    st.divider()

    if st.button("Desconectar"):
        cliente.desconectar()
        st.rerun()

# ============================================================
# Área principal do chat
# ============================================================

if not topico_ativo:
    st.info("Crie ou escolha um tópico para começar.")

else:
    st.subheader(f"Tópico: {topico_ativo}")

    mensagens = st.session_state.mensagens_por_topico.get(topico_ativo, [])

    if mensagens:
        for mensagem in mensagens:
            st.write(f"💬 {mensagem}")
    else:
        st.info("Nenhuma mensagem neste tópico ainda.")

    st.divider()

    inscrito = topico_ativo in st.session_state.topicos_inscritos
    possui_chave = topico_ativo in cliente.chaves_topicos

    if not inscrito:
        st.warning("Você precisa se inscrever neste tópico para enviar mensagens.")

    elif not possui_chave:
        st.warning(
            "Você está inscrito, mas não possui a chave E2E deste tópico. "
            "Importe a chave para conseguir enviar e ler mensagens."
        )

    else:
        with st.form("formulario_mensagem", clear_on_submit=True):
            texto = st.text_input("Mensagem:")

            enviar = st.form_submit_button("Enviar")

            if enviar:
                if texto.strip():
                    sucesso, mensagem = cliente.publicar(
                        topico_ativo,
                        texto.strip()
                    )

                    if sucesso:
                        hora = datetime.now().strftime("%H:%M")

                        mensagem_local = (
                            f"{cliente.nome_cliente}: {texto.strip()} [{hora}]"
                        )

                        st.session_state.mensagens_por_topico.setdefault(
                            topico_ativo,
                            []
                        ).append(mensagem_local)

                        st.rerun()
                    else:
                        st.error(mensagem)
                else:
                    st.warning("Digite uma mensagem antes de enviar.")

# ============================================================
# Mensagens do sistema
# ============================================================

mensagens_sistema = st.session_state.mensagens_por_topico.get("Sistema", [])

if mensagens_sistema:
    with st.expander("Mensagens do sistema"):
        for mensagem in mensagens_sistema[-10:]:
            st.write(mensagem)