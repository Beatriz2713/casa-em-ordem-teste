from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
import string
import os
from datetime import date, timedelta
import calendar
import traceback


# =========================================================
# CONFIGURAÇÃO DA APLICAÇÃO
# =========================================================

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "casa_em_ordem.db")

app.secret_key = "casa-em-ordem-chave"


# =========================================================
# BANCO DE DADOS
# =========================================================
def conectar_banco():

    conexao = sqlite3.connect(
        DATABASE,
        timeout=10
    )

    conexao.row_factory = sqlite3.Row

    # Faz o SQLite esperar caso o banco esteja temporariamente ocupado
    conexao.execute("PRAGMA busy_timeout = 10000")

    # Ativa as chaves estrangeiras
    conexao.execute("PRAGMA foreign_keys = ON")

    return conexao

   



# =========================================================
# FUNÇÕES AUXILIARES DO RODÍZIO
# =========================================================

def obter_proximo_mes():
    hoje = date.today()

    if hoje.month == 12:
        return hoje.year + 1, 1

    return hoje.year, hoje.month + 1


def obter_semanas_mes(ano, mes):
    """
    Retorna as semanas de segunda a domingo
    cujo primeiro dia pertence ao mês escolhido.
    """

    primeiro_dia = date(ano, mes, 1)
    ultimo_dia = date(
        ano,
        mes,
        calendar.monthrange(ano, mes)[1]
    )

    # Primeiro dia do mês que seja segunda-feira
    inicio = primeiro_dia + timedelta(
        days=(7 - primeiro_dia.weekday()) % 7
    )

    semanas = []

    while inicio <= ultimo_dia:
        fim = inicio + timedelta(days=6)

        semanas.append({
            "inicio": inicio,
            "fim": fim
        })

        inicio += timedelta(days=7)

    return semanas


def distribuir_tarefas(membros, tarefas, quantidade_semanas,
                       historico):
    """
    Distribui tarefas buscando equilibrar a carga
    e evitar repetir a mesma tarefa para a mesma pessoa
    em semanas consecutivas.
    """

    carga = {m["id_usuario"]: 0 for m in membros}

    distribuicoes = []

    atribuicoes_anteriores = {}

    # Tarefas mais pesadas são distribuídas primeiro
    tarefas_ordenadas = sorted(
        tarefas,
        key=lambda t: float(t["peso"] or 1),
        reverse=True
    )

    for numero_semana in range(quantidade_semanas):

        semana_atual = []

        for tarefa in tarefas_ordenadas:

            candidatos = []

            for membro in membros:

                id_usuario = membro["id_usuario"]

                # Evita repetir a mesma tarefa
                # para a mesma pessoa em semanas seguidas
                repetiu = (
                    atribuicoes_anteriores.get(
                        tarefa["id_tarefa"]
                    ) == id_usuario
                )

                penalidade = 100000 if repetiu else 0

                pontuacao = (
                    carga[id_usuario]
                    + penalidade
                )

                candidatos.append(
                    (pontuacao, id_usuario)
                )

            candidatos.sort()

            menor_pontuacao = candidatos[0][0]

            melhores = [
                candidato
                for candidato in candidatos
                if candidato[0] == menor_pontuacao
            ]

            escolhido = melhores[0][1]

            semana_atual.append({
                "id_tarefa": tarefa["id_tarefa"],
                "id_usuario": escolhido
            })

            carga[escolhido] += float(
                tarefa["peso"] or 1
            )

            atribuicoes_anteriores[
                tarefa["id_tarefa"]
            ] = escolhido

        distribuicoes.append(semana_atual)

    return distribuicoes






def garantir_coluna_realizador(conexao):
    """Adiciona o campo do realizador, caso ainda não exista."""

    colunas = conexao.execute(
        "PRAGMA table_info(EXECUCAO_TAREFA)"
    ).fetchall()

    nomes_colunas = [coluna["name"] for coluna in colunas]

    if "id_usuario_realizador" not in nomes_colunas:
        conexao.execute("""
            ALTER TABLE EXECUCAO_TAREFA
            ADD COLUMN id_usuario_realizador INTEGER
            REFERENCES USUARIO(id_usuario)
        """)





# =========================================================
# GERAR CÓDIGO
# =========================================================
def gerar_codigo_familia(conexao):
    caracteres = string.ascii_uppercase + string.digits

    while True:
        codigo = "CASA-" + "".join(
            secrets.choice(caracteres)
            for _ in range(5)
        )

        existente = conexao.execute(
            """
            SELECT id_familia
            FROM FAMILIA
            WHERE codigo_familia = ?
            """,
            (codigo,)
        ).fetchone()

        if not existente:
            return codigo


# =========================================================
# PÁGINA INICIAL
# =========================================================
@app.route("/")
def inicio():
    return redirect(url_for("cadastro"))


# =========================================================
# CADASTRO DE NOVA FAMÍLIA
# =========================================================
@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():

    if request.method == "POST":

        nome_familia = request.form["nome_familia"].strip()
        nome_usuario = request.form["nome_usuario"].strip()
        email = request.form["email"].strip()
        senha = request.form["senha"]

        # Verifica os campos
        if not nome_familia or not nome_usuario or not email or not senha:
            flash("Preencha todos os campos.")
            return redirect(url_for("cadastro"))

        conexao = conectar_banco()

        try:

            # Verifica se o e-mail já existe
            usuario_existente = conexao.execute(
                """
                SELECT id_usuario
                FROM USUARIO
                WHERE email = ?
                """,
                (email,)
            ).fetchone()

            if usuario_existente:
                flash("Este e-mail já está cadastrado.")
                return redirect(url_for("cadastro"))

            # Gera o código da família
            codigo_familia = gerar_codigo_familia(conexao)

            # Cria a família
            cursor = conexao.execute(
                """
                INSERT INTO FAMILIA
                (
                    nome,
                    codigo_familia,
                    data_cadastro
                )
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    nome_familia,
                    codigo_familia
                )
            )

            id_familia = cursor.lastrowid

            # Criptografa a senha
            senha_hash = generate_password_hash(senha)

            # Cria o primeiro usuário como administrador
            conexao.execute(
                """
                INSERT INTO USUARIO
                (
                    id_familia,
                    nome,
                    email,
                    senha,
                    tipo_usuario,
                    ativo,
                    data_cadastro
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    id_familia,
                    nome_usuario,
                    email,
                    senha_hash,
                    "ADMINISTRADOR",
                    1
                )
            )

            conexao.commit()

            flash("Família cadastrada com sucesso!")

            return redirect(url_for("cadastro"))

        except sqlite3.Error as erro:

            conexao.rollback()

            print("Erro no cadastro:", erro)

            flash("Ocorreu um erro ao realizar o cadastro.")

        finally:
            conexao.close()

    return render_template("cadastro.html")


# =========================================================
# ENTRAR EM UMA FAMÍLIA EXISTENTE
# =========================================================
@app.route("/entrar-familia", methods=["GET", "POST"])
def entrar_familia():

    if request.method == "POST":

        codigo_familia = request.form["codigo_familia"].strip().upper()
        nome_usuario = request.form["nome_usuario"].strip()
        email = request.form["email"].strip()
        senha = request.form["senha"]

        # Verifica os campos
        if not codigo_familia or not nome_usuario or not email or not senha:
            flash("Preencha todos os campos.")
            return redirect(url_for("entrar_familia"))

        conexao = conectar_banco()

        try:

            # Procura a família pelo código
            # Remove espaços e quebras de linha extras
            familia = conexao.execute(
                """
                SELECT id_familia
                FROM FAMILIA
                WHERE TRIM(
                    REPLACE(
                        REPLACE(codigo_familia, char(13), ''),
                        char(10),
                        ''
                    )
                ) = ?
                """,
                (codigo_familia,)
            ).fetchone()

            if not familia:
                flash("Código da família não encontrado.")
                return redirect(url_for("entrar_familia"))

            # Verifica se o e-mail já existe
            usuario_existente = conexao.execute(
                """
                SELECT id_usuario
                FROM USUARIO
                WHERE email = ?
                """,
                (email,)
            ).fetchone()

            if usuario_existente:
                flash("Este e-mail já está cadastrado.")
                return redirect(url_for("entrar_familia"))

            # Criptografa a senha
            senha_hash = generate_password_hash(senha)

            # Cria o novo membro
            conexao.execute(
                """
                INSERT INTO USUARIO
                (
                    id_familia,
                    nome,
                    email,
                    senha,
                    tipo_usuario,
                    ativo,
                    data_cadastro
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    familia["id_familia"],
                    nome_usuario,
                    email,
                    senha_hash,
                    "MEMBRO",
                    1
                )
            )

            conexao.commit()

            flash("Você entrou na família com sucesso!")

            return redirect(url_for("login"))

        except sqlite3.Error as erro:

            conexao.rollback()

            print("Erro ao entrar na família:", erro)

            flash("Ocorreu um erro ao entrar na família.")

        finally:
            conexao.close()

    return render_template("entrar_familia.html")


# =========================================================
# LOGIN
# =========================================================
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"].strip()
        senha = request.form["senha"]

        conexao = conectar_banco()

        try:

            usuario = conexao.execute(
                """
                SELECT *
                FROM USUARIO
                WHERE email = ?
                  AND ativo = 1
                """,
                (email,)
            ).fetchone()

        finally:
            conexao.close()

        if usuario and check_password_hash(
            usuario["senha"],
            senha
        ):

            # Salva informações do usuário na sessão
            session["id_usuario"] = usuario["id_usuario"]
            session["id_familia"] = usuario["id_familia"]
            session["nome_usuario"] = usuario["nome"]
            session["tipo_usuario"] = usuario["tipo_usuario"]

            return redirect(url_for("dashboard"))

        flash("E-mail ou senha incorretos.")

        return redirect(url_for("login"))

    return render_template("login.html")


# =========================================================
# MINHA FAMÍLIA
# =========================================================
@app.route("/familia")
def familia():

    # Usuário precisa estar logado
    if "id_usuario" not in session:
        return redirect(url_for("login"))

    conexao = conectar_banco()

    try:

        # Busca a família do usuário logado
        familia = conexao.execute(
            """
            SELECT
                id_familia,
                nome,
                codigo_familia
            FROM FAMILIA
            WHERE id_familia = ?
            """,
            (session["id_familia"],)
        ).fetchone()

        # Busca todos os membros da mesma família
        membros = conexao.execute(
            """
            SELECT
                id_usuario,
                nome,
                email,
                tipo_usuario,
                ativo,
                foto
            FROM USUARIO
            WHERE id_familia = ?
            ORDER BY
                CASE
                    WHEN tipo_usuario = 'ADMINISTRADOR' THEN 0
                    ELSE 1
                END,
                nome
            """,
            (session["id_familia"],)
        ).fetchall()

    finally:
        conexao.close()

    return render_template(
        "familia.html",
        familia=familia,
        membros=membros
    )


#PERFIL
@app.route("/perfil")
def perfil():
    if "id_usuario" not in session:
        return redirect(url_for("login"))

    conexao = conectar_banco()

    try:
        usuario = conexao.execute(
            """
            SELECT *
            FROM USUARIO
            WHERE id_usuario = ?
              AND id_familia = ?
            """,
            (
                session["id_usuario"],
                session["id_familia"]
            )
        ).fetchone()

        familia = conexao.execute(
            """
            SELECT *
            FROM FAMILIA
            WHERE id_familia = ?
            """,
            (session["id_familia"],)
        ).fetchone()

    finally:
        conexao.close()

    if not usuario or not familia:
        session.clear()
        return redirect(url_for("login"))

    return render_template(
        "perfil.html",
        usuario=usuario,
        familia=familia
    )


#EDITAR PERFIL
@app.route("/perfil/editar", methods=["GET", "POST"])
def editar_perfil():
    if "id_usuario" not in session:
        return redirect(url_for("login"))

    conexao = conectar_banco()

    try:
        usuario = conexao.execute(
            """
            SELECT *
            FROM USUARIO
            WHERE id_usuario = ?
              AND id_familia = ?
            """,
            (
                session["id_usuario"],
                session["id_familia"]
            )
        ).fetchone()

        if not usuario:
            session.clear()
            return redirect(url_for("login"))

        if request.method == "POST":
            nome = request.form["nome"].strip()
            email = request.form["email"].strip()

            if not nome or not email:
                flash("Preencha todos os campos.")
                return redirect(url_for("editar_perfil"))

            outro_usuario = conexao.execute(
                """
                SELECT id_usuario
                FROM USUARIO
                WHERE email = ?
                  AND id_usuario != ?
                """,
                (
                    email,
                    session["id_usuario"]
                )
            ).fetchone()

            if outro_usuario:
                flash("Este e-mail já está sendo usado por outro usuário.")
                return redirect(url_for("editar_perfil"))

            conexao.execute(
                """
                UPDATE USUARIO
                SET nome = ?,
                    email = ?
                WHERE id_usuario = ?
                  AND id_familia = ?
                """,
                (
                    nome,
                    email,
                    session["id_usuario"],
                    session["id_familia"]
                )
            )

            conexao.commit()

            session["nome_usuario"] = nome

            flash("Perfil atualizado com sucesso!")

            return redirect(url_for("perfil"))

    except sqlite3.Error as erro:
        conexao.rollback()
        print("Erro ao editar perfil:", erro)

        flash("Ocorreu um erro ao atualizar o perfil.")

    finally:
        conexao.close()

    return render_template(
        "editar_perfil.html",
        usuario=usuario
    )


#SENHA DO PERFIL
@app.route("/perfil/senha", methods=["GET", "POST"])
def alterar_senha():
    if "id_usuario" not in session:
        return redirect(url_for("login"))

    conexao = conectar_banco()

    try:
        usuario = conexao.execute(
            """
            SELECT *
            FROM USUARIO
            WHERE id_usuario = ?
              AND id_familia = ?
            """,
            (
                session["id_usuario"],
                session["id_familia"]
            )
        ).fetchone()

        if not usuario:
            session.clear()
            return redirect(url_for("login"))

        if request.method == "POST":

            senha_atual = request.form["senha_atual"]
            nova_senha = request.form["nova_senha"]
            confirmar_senha = request.form["confirmar_senha"]

            # Verifica a senha atual
            if not check_password_hash(
                usuario["senha"],
                senha_atual
            ):
                flash("A senha atual está incorreta.")
                return redirect(url_for("alterar_senha"))

            # Verifica se as novas senhas são iguais
            if nova_senha != confirmar_senha:
                flash("A confirmação da nova senha não confere.")
                return redirect(url_for("alterar_senha"))

            # Verifica se a nova senha não está vazia
            if not nova_senha:
                flash("Digite uma nova senha.")
                return redirect(url_for("alterar_senha"))

            # Evita usar a mesma senha
            if check_password_hash(
                usuario["senha"],
                nova_senha
            ):
                flash("A nova senha precisa ser diferente da atual.")
                return redirect(url_for("alterar_senha"))

            nova_senha_hash = generate_password_hash(nova_senha)

            conexao.execute(
                """
                UPDATE USUARIO
                SET senha = ?
                WHERE id_usuario = ?
                  AND id_familia = ?
                """,
                (
                    nova_senha_hash,
                    session["id_usuario"],
                    session["id_familia"]
                )
            )

            conexao.commit()

            flash("Senha alterada com sucesso!")

            return redirect(url_for("perfil"))

    except sqlite3.Error as erro:

        conexao.rollback()

        print("Erro ao alterar senha:", erro)

        flash("Ocorreu um erro ao alterar a senha.")

    finally:
        conexao.close()

    return render_template("alterar_senha.html")


# =========================================================
# TAREFAS
# =========================================================
@app.route("/tarefas")
def tarefas():

    if "id_usuario" not in session:
        return redirect(url_for("login"))

    conexao = conectar_banco()

    try:

        tarefas = conexao.execute(
            """
            SELECT *
            FROM TAREFA
            WHERE id_familia = ?
              AND ativa = 1
            ORDER BY nome
            """,
            (session["id_familia"],)
        ).fetchall()

    finally:
        conexao.close()

    return render_template(
        "tarefas.html",
        tarefas=tarefas
    )


# =========================================================
# ADICIONAR TAREFA
# =========================================================
@app.route("/tarefas/nova", methods=["GET", "POST"])
def nova_tarefa():

    if "id_usuario" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":

        nome = request.form["nome"].strip()
        descricao = request.form["descricao"].strip()
        tipo = request.form["tipo"]
        participa_rodizio = request.form["participa_rodizio"]
        peso = request.form["peso"]

        if not nome:
            flash("Digite o nome da tarefa.")
            return redirect(url_for("nova_tarefa"))

        conexao = conectar_banco()

        try:

            conexao.execute(
                """
                INSERT INTO TAREFA
                (
                    id_familia,
                    id_usuario_criador,
                    nome,
                    descricao,
                    tipo,
                    participa_rodizio,
                    peso,
                    ativa,
                    data_cadastro
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    session["id_familia"],
                    session["id_usuario"],
                    nome,
                    descricao,
                    tipo,
                    int(participa_rodizio),
                    float(peso),
                    1
                )
            )

            conexao.commit()

            flash("Tarefa cadastrada com sucesso!")

            return redirect(url_for("tarefas"))

        except sqlite3.Error as erro:

            conexao.rollback()

            print("Erro ao cadastrar tarefa:", erro)

            flash("Ocorreu um erro ao cadastrar a tarefa.")

        finally:
            conexao.close()

    return render_template("nova_tarefa.html")


# =========================================================
# EDITAR TAREFA
# =========================================================
@app.route(
    "/tarefas/editar/<int:id_tarefa>",
    methods=["GET", "POST"]
)
def editar_tarefa(id_tarefa):

    if "id_usuario" not in session:
        return redirect(url_for("login"))

    # Apenas administradores podem editar
    if session["tipo_usuario"] != "ADMINISTRADOR":

        flash("Apenas o administrador pode editar tarefas.")

        return redirect(url_for("tarefas"))

    conexao = conectar_banco()

    try:

        tarefa = conexao.execute(
            """
            SELECT *
            FROM TAREFA
            WHERE id_tarefa = ?
              AND id_familia = ?
              AND ativa = 1
            """,
            (
                id_tarefa,
                session["id_familia"]
            )
        ).fetchone()

        if not tarefa:

            flash("Tarefa não encontrada.")

            return redirect(url_for("tarefas"))

        if request.method == "POST":

            nome = request.form["nome"].strip()
            descricao = request.form["descricao"].strip()
            tipo = request.form["tipo"]
            participa_rodizio = request.form["participa_rodizio"]
            peso = request.form["peso"]

            if not nome:

                flash("Digite o nome da tarefa.")

                return redirect(
                    url_for(
                        "editar_tarefa",
                        id_tarefa=id_tarefa
                    )
                )

            conexao.execute(
                """
                UPDATE TAREFA
                SET nome = ?,
                    descricao = ?,
                    tipo = ?,
                    participa_rodizio = ?,
                    peso = ?
                WHERE id_tarefa = ?
                  AND id_familia = ?
                """,
                (
                    nome,
                    descricao,
                    tipo,
                    int(participa_rodizio),
                    float(peso),
                    id_tarefa,
                    session["id_familia"]
                )
            )

            conexao.commit()

            flash("Tarefa atualizada com sucesso!")

            return redirect(url_for("tarefas"))

    except sqlite3.Error as erro:

        conexao.rollback()

        print("Erro ao editar tarefa:", erro)

        flash("Ocorreu um erro ao atualizar a tarefa.")

        return redirect(
            url_for(
                "editar_tarefa",
                id_tarefa=id_tarefa
            )
        )

    finally:
        conexao.close()

    return render_template(
        "editar_tarefa.html",
        tarefa=tarefa
    )


# =========================================================
# DESATIVAR TAREFA
# =========================================================
@app.route(
    "/tarefas/desativar/<int:id_tarefa>",
    methods=["POST"]
)
def desativar_tarefa(id_tarefa):

    if "id_usuario" not in session:
        return redirect(url_for("login"))

    # Apenas administradores podem desativar
    if session["tipo_usuario"] != "ADMINISTRADOR":

        flash("Apenas o administrador pode desativar tarefas.")

        return redirect(url_for("tarefas"))

    conexao = conectar_banco()

    try:

        tarefa = conexao.execute(
            """
            SELECT id_tarefa
            FROM TAREFA
            WHERE id_tarefa = ?
              AND id_familia = ?
              AND ativa = 1
            """,
            (
                id_tarefa,
                session["id_familia"]
            )
        ).fetchone()

        if not tarefa:

            flash("Tarefa não encontrada.")

            return redirect(url_for("tarefas"))

        conexao.execute(
            """
            UPDATE TAREFA
            SET ativa = 0
            WHERE id_tarefa = ?
              AND id_familia = ?
            """,
            (
                id_tarefa,
                session["id_familia"]
            )
        )

        conexao.commit()

        flash("Tarefa desativada com sucesso!")

    except sqlite3.Error as erro:

        conexao.rollback()

        print("Erro ao desativar tarefa:", erro)

        flash("Ocorreu um erro ao desativar a tarefa.")

    finally:
        conexao.close()

    return redirect(url_for("tarefas"))



# =========================================================
# EXECUÇÃO DAS TAREFAS
# =========================================================
@app.route("/tarefas/execucao")
def execucao_tarefas():

    if "id_usuario" not in session:
        return redirect(url_for("login"))

    conexao = conectar_banco()

    try:
        garantir_coluna_realizador(conexao)
        conexao.commit()

        execucoes = conexao.execute("""
            SELECT
                e.id_execucao,
                e.status,
                e.data_inicio,
                e.data_conclusao,
                e.data_prevista,
                e.observacao,

                t.nome AS nome_tarefa,
                t.descricao AS descricao_tarefa,

                responsavel.nome AS nome_responsavel,
                realizador.nome AS nome_realizador

            FROM EXECUCAO_TAREFA e

            INNER JOIN TAREFA t
                ON e.id_tarefa = t.id_tarefa

            LEFT JOIN USUARIO responsavel
                ON e.id_usuario = responsavel.id_usuario

            LEFT JOIN USUARIO realizador
                ON e.id_usuario_realizador = realizador.id_usuario

            WHERE t.id_familia = ?

            ORDER BY
                CASE e.status
                    WHEN 'PENDENTE' THEN 1
                    WHEN 'EM_ANDAMENTO' THEN 2
                    WHEN 'CONCLUIDA' THEN 3
                    ELSE 4
                END,
                e.data_prevista
        """, (session["id_familia"],)).fetchall()

    except sqlite3.Error as erro:
        print("Erro ao buscar execuções:", erro)
        flash("Não foi possível carregar as tarefas.")
        execucoes = []

    finally:
        conexao.close()

    return render_template(
        "execucao_tarefas.html",
        execucoes=execucoes
    )


# =========================================================
# ATUALIZAR STATUS DA TAREFA
# =========================================================
@app.route(
    "/tarefas/execucao/atualizar/<int:id_execucao>",
    methods=["POST"]
)
def atualizar_execucao(id_execucao):

    if "id_usuario" not in session:
        return redirect(url_for("login"))

    novo_status = request.form.get("status")

    status_permitidos = [
        "PENDENTE",
        "EM_ANDAMENTO",
        "CONCLUIDA"
    ]

    if novo_status not in status_permitidos:
        flash("Status inválido.")
        return redirect(url_for("execucao_tarefas"))

    conexao = conectar_banco()

    try:
        garantir_coluna_realizador(conexao)

        execucao = conexao.execute("""
            SELECT e.id_execucao
            FROM EXECUCAO_TAREFA e

            INNER JOIN TAREFA t
                ON e.id_tarefa = t.id_tarefa

            WHERE e.id_execucao = ?
              AND t.id_familia = ?
        """, (
            id_execucao,
            session["id_familia"]
        )).fetchone()

        if not execucao:
            flash("Tarefa não encontrada.")
            return redirect(url_for("execucao_tarefas"))

        if novo_status == "PENDENTE":

            conexao.execute("""
                UPDATE EXECUCAO_TAREFA
                SET status = ?,
                    data_inicio = NULL,
                    data_conclusao = NULL,
                    id_usuario_realizador = NULL

                WHERE id_execucao = ?
            """, (novo_status, id_execucao))

        elif novo_status == "EM_ANDAMENTO":

            conexao.execute("""
                UPDATE EXECUCAO_TAREFA
                SET status = ?,
                    data_inicio = COALESCE(
                        data_inicio,
                        CURRENT_TIMESTAMP
                    ),
                    data_conclusao = NULL,
                    id_usuario_realizador = NULL

                WHERE id_execucao = ?
            """, (novo_status, id_execucao))

        elif novo_status == "CONCLUIDA":

            conexao.execute("""
                UPDATE EXECUCAO_TAREFA
                SET status = ?,
                    data_inicio = COALESCE(
                        data_inicio,
                        CURRENT_TIMESTAMP
                    ),
                    data_conclusao = CURRENT_TIMESTAMP,
                    id_usuario_realizador = ?

                WHERE id_execucao = ?
            """, (
                novo_status,
                session["id_usuario"],
                id_execucao
            ))

        conexao.commit()

        flash("Andamento da tarefa atualizado!")

    except sqlite3.Error as erro:

        conexao.rollback()

        print("Erro ao atualizar execução:", erro)

        flash("Não foi possível atualizar a tarefa.")

    finally:
        conexao.close()

    return redirect(url_for("execucao_tarefas"))




# =========================================================
# GERAR RODÍZIO
# =========================================================
@app.route("/rodizio/gerar", methods=["POST"])
def gerar_rodizio():

    if "id_usuario" not in session:
        return redirect(url_for("login"))

    if session.get("tipo_usuario") != "ADMINISTRADOR":
        flash("Apenas o administrador pode gerar o rodízio.")
        return redirect(url_for("dashboard"))

    ano = request.form.get("ano", type=int)
    mes = request.form.get("mes", type=int)

    if not ano or not mes or mes < 1 or mes > 12:
        ano, mes = obter_proximo_mes()

    semanas = obter_semanas_mes(ano, mes)

    if not semanas:
        flash("Não foi possível encontrar semanas para esse mês.")
        return redirect(url_for("dashboard"))

    conexao = conectar_banco()

    try:
        # Busca membros ativos da família
        membros = conexao.execute("""
            SELECT id_usuario, nome
            FROM USUARIO
            WHERE id_familia = ?
              AND ativo = 1
            ORDER BY nome
        """, (session["id_familia"],)).fetchall()

        # Busca tarefas ativas que participam do rodízio
        tarefas = conexao.execute("""
            SELECT id_tarefa, nome, peso
            FROM TAREFA
            WHERE id_familia = ?
              AND ativa = 1
              AND participa_rodizio = 1
            ORDER BY nome
        """, (session["id_familia"],)).fetchall()

        if not membros:
            flash("Não existem membros ativos na família.")
            return redirect(url_for("dashboard"))

        if not tarefas:
            flash("Não existem tarefas habilitadas para o rodízio.")
            return redirect(url_for("tarefas"))

        # Impede gerar outro rascunho se o mês já foi confirmado
        confirmado = conexao.execute("""
            SELECT id_semana
            FROM SEMANA_RODIZIO
            WHERE id_familia = ?
              AND mes_referencia = ?
              AND ano_referencia = ?
              AND status = 'CONFIRMADO'
            LIMIT 1
        """, (
            session["id_familia"],
            mes,
            ano
        )).fetchone()

        if confirmado:
            flash("O rodízio desse mês já foi confirmado.")
            return redirect(url_for("visualizar_rodizio",
                                    ano=ano, mes=mes))

        # Remove eventual rascunho anterior do mesmo mês
        rascunhos = conexao.execute("""
            SELECT id_semana
            FROM SEMANA_RODIZIO
            WHERE id_familia = ?
              AND mes_referencia = ?
              AND ano_referencia = ?
              AND status = 'RASCUNHO'
        """, (
            session["id_familia"],
            mes,
            ano
        )).fetchall()

        for rascunho in rascunhos:
            conexao.execute("""
                DELETE FROM RODIZIO
                WHERE id_semana = ?
            """, (rascunho["id_semana"],))

            conexao.execute("""
                DELETE FROM SEMANA_RODIZIO
                WHERE id_semana = ?
            """, (rascunho["id_semana"],))

        # Recupera responsáveis da última semana anterior
        ultima_semana = conexao.execute("""
            SELECT s.id_semana
            FROM SEMANA_RODIZIO s
            WHERE s.id_familia = ?
              AND s.data_inicio < ?
              AND s.status = 'CONFIRMADO'
            ORDER BY s.data_inicio DESC
            LIMIT 1
        """, (
            session["id_familia"],
            semanas[0]["inicio"].isoformat()
        )).fetchone()

        historico = {}

        if ultima_semana:
            registros = conexao.execute("""
                SELECT id_tarefa, id_usuario
                FROM RODIZIO
                WHERE id_semana = ?
            """, (ultima_semana["id_semana"],)).fetchall()

            historico = {
                registro["id_tarefa"]: registro["id_usuario"]
                for registro in registros
            }

        distribuicoes = distribuir_tarefas(
            membros,
            tarefas,
            len(semanas),
            historico
        )

        # Salva a prévia como rascunho
        for indice, semana in enumerate(semanas):

            cursor = conexao.execute("""
                INSERT INTO SEMANA_RODIZIO (
                    id_familia,
                    data_inicio,
                    data_fim,
                    mes_referencia,
                    ano_referencia,
                    status
                )
                VALUES (?, ?, ?, ?, ?, 'RASCUNHO')
            """, (
                session["id_familia"],
                semana["inicio"].isoformat(),
                semana["fim"].isoformat(),
                mes,
                ano
            ))

            id_semana = cursor.lastrowid

            for atribuicao in distribuicoes[indice]:

                conexao.execute("""
                    INSERT INTO RODIZIO (
                        id_semana,
                        id_tarefa,
                        id_usuario,
                        ajustado_manualmente
                    )
                    VALUES (?, ?, ?, 0)
                """, (
                    id_semana,
                    atribuicao["id_tarefa"],
                    atribuicao["id_usuario"]
                ))

        conexao.commit()

        flash("Prévia do rodízio gerada com sucesso!")

    except sqlite3.Error as erro:
            conexao.rollback()

            print("\n========== ERRO AO GERAR RODÍZIO ==========")
            print("Mensagem:", erro)
            traceback.print_exc()
            print("============================================\n")

            flash("Ocorreu um erro ao gerar o rodízio.")

    finally:
        conexao.close()

    return redirect(url_for(
        "visualizar_rodizio",
        ano=ano,
        mes=mes
    ))



# =========================================================
# VISUALIZAR RODÍZIO
# =========================================================
@app.route("/rodizio")
def visualizar_rodizio():

    if "id_usuario" not in session:
        return redirect(url_for("login"))

    ano = request.args.get("ano", type=int)
    mes = request.args.get("mes", type=int)

    if not ano or not mes:
        ano, mes = obter_proximo_mes()

    conexao = conectar_banco()

    try:
        semanas = conexao.execute("""
            SELECT *
            FROM SEMANA_RODIZIO
            WHERE id_familia = ?
              AND mes_referencia = ?
              AND ano_referencia = ?
            ORDER BY data_inicio
        """, (
            session["id_familia"],
            mes,
            ano
        )).fetchall()

        distribuicao = []

        for semana in semanas:

            atribuicoes = conexao.execute("""
                SELECT
                    r.id_rodizio,
                    r.id_tarefa,
                    r.id_usuario,
                    r.ajustado_manualmente,
                    t.nome AS nome_tarefa,
                    u.nome AS nome_usuario

                FROM RODIZIO r

                INNER JOIN TAREFA t
                    ON r.id_tarefa = t.id_tarefa

                INNER JOIN USUARIO u
                    ON r.id_usuario = u.id_usuario

                WHERE r.id_semana = ?

                ORDER BY t.nome
            """, (semana["id_semana"],)).fetchall()

            distribuicao.append({
                "semana": semana,
                "tarefas": atribuicoes
            })

        # Busca todos os membros ativos da família
        membros = conexao.execute("""
            SELECT id_usuario, nome
            FROM USUARIO
            WHERE id_familia = ?
              AND ativo = 1
            ORDER BY nome
        """, (session["id_familia"],)).fetchall()

    finally:
        conexao.close()

    return render_template(
        "rodizio.html",
        distribuicao=distribuicao,
        membros=membros,
        mes=mes,
        ano=ano
    )


# =========================================================
# CONFIRMAR RODÍZIO
# =========================================================
@app.route(
    "/rodizio/confirmar/<int:ano>/<int:mes>",
    methods=["POST"]
)
def confirmar_rodizio(ano, mes):

    if "id_usuario" not in session:
        return redirect(url_for("login"))

    if session.get("tipo_usuario") != "ADMINISTRADOR":
        flash("Apenas o administrador pode confirmar o rodízio.")
        return redirect(url_for("dashboard"))

    conexao = conectar_banco()

    try:
        semanas = conexao.execute("""
            SELECT id_semana, data_inicio
            FROM SEMANA_RODIZIO
            WHERE id_familia = ?
              AND mes_referencia = ?
              AND ano_referencia = ?
              AND status = 'RASCUNHO'
            ORDER BY data_inicio
        """, (
            session["id_familia"],
            mes,
            ano
        )).fetchall()

        if not semanas:
            flash("Não existe um rascunho para confirmar.")
            return redirect(url_for(
                "visualizar_rodizio",
                ano=ano,
                mes=mes
            ))

        for semana in semanas:

            atribuicoes = conexao.execute("""
                SELECT id_rodizio, id_tarefa, id_usuario
                FROM RODIZIO
                WHERE id_semana = ?
            """, (semana["id_semana"],)).fetchall()

            for atribuicao in atribuicoes:

                # Evita criar uma execução duplicada
                existente = conexao.execute("""
                    SELECT id_execucao
                    FROM EXECUCAO_TAREFA
                    WHERE id_rodizio = ?
                """, (atribuicao["id_rodizio"],)).fetchone()

                if not existente:
                    conexao.execute("""
                        INSERT INTO EXECUCAO_TAREFA (
                            id_tarefa,
                            id_usuario,
                            id_rodizio,
                            status,
                            data_prevista
                        )
                        VALUES (?, ?, ?, 'PENDENTE', ?)
                    """, (
                        atribuicao["id_tarefa"],
                        atribuicao["id_usuario"],
                        atribuicao["id_rodizio"],
                        semana["data_inicio"]
                    ))

            conexao.execute("""
                UPDATE SEMANA_RODIZIO
                SET status = 'CONFIRMADO'
                WHERE id_semana = ?
            """, (semana["id_semana"],))

        conexao.commit()

        flash("Rodízio confirmado! As tarefas foram distribuídas.")

    except sqlite3.Error as erro:
        conexao.rollback()
        print("Erro ao confirmar rodízio:", erro)
        flash("Ocorreu um erro ao confirmar o rodízio.")

    finally:
        conexao.close()

    return redirect(url_for(
        "visualizar_rodizio",
        ano=ano,
        mes=mes
    ))




# =========================================================
# AJUSTAR MANUALMENTE UMA TAREFA DO RODÍZIO
# =========================================================
@app.route(
    "/rodizio/ajustar/<int:id_rodizio>",
    methods=["POST"]
)
def ajustar_rodizio(id_rodizio):

    if "id_usuario" not in session:
        return redirect(url_for("login"))

    if session["tipo_usuario"] != "ADMINISTRADOR":
        flash("Apenas o administrador pode ajustar o rodízio.")
        return redirect(url_for("visualizar_rodizio"))

    conexao = conectar_banco()

    try:
        # Verifica se a atribuição pertence à família
        # e se a semana ainda está em rascunho.
        atribuicao = conexao.execute(
            """
            SELECT R.id_rodizio, S.status
            FROM RODIZIO R
            INNER JOIN SEMANA_RODIZIO S
                ON R.id_semana = S.id_semana
            WHERE R.id_rodizio = ?
              AND S.id_familia = ?
            """,
            (
                id_rodizio,
                session["id_familia"]
            )
        ).fetchone()

        if not atribuicao:
            flash("Atribuição não encontrada.")

            return redirect(url_for("visualizar_rodizio"))

        if atribuicao["status"] != "RASCUNHO":
            flash("Só é possível ajustar um rodízio ainda não confirmado.")

            return redirect(url_for("visualizar_rodizio"))

        # Recebe o novo responsável escolhido
        novo_usuario = request.form.get(
            "id_usuario",
            type=int
        )

        if not novo_usuario:
            flash("Selecione um membro da família.")

            return redirect(url_for("visualizar_rodizio"))

        # Verifica se o membro pertence à família e está ativo
        membro = conexao.execute(
            """
            SELECT id_usuario
            FROM USUARIO
            WHERE id_usuario = ?
              AND id_familia = ?
              AND ativo = 1
            """,
            (
                novo_usuario,
                session["id_familia"]
            )
        ).fetchone()

        if not membro:
            flash("Membro inválido.")

            return redirect(url_for("visualizar_rodizio"))

        # Altera somente esta atribuição
        conexao.execute(
            """
            UPDATE RODIZIO
            SET id_usuario = ?,
                ajustado_manualmente = 1
            WHERE id_rodizio = ?
            """,
            (
                novo_usuario,
                id_rodizio
            )
        )

        conexao.commit()

        flash("Responsável atualizado com sucesso!")

    except sqlite3.Error as erro:
        conexao.rollback()

        print("Erro ao ajustar rodízio:", erro)

        flash("Ocorreu um erro ao ajustar o responsável.")

    finally:
        conexao.close()

    return redirect(url_for("visualizar_rodizio"))





# =========================================================
# PRODUTOS NOVOS
# =========================================================
@app.route("/produtos/novo", methods=["GET", "POST"])
def novo_produto():
    if "id_usuario" not in session:
        return redirect(url_for("login"))

    conexao = conectar_banco()

    print("BANCO UTILIZADO:", DATABASE)

    print("BANCO CONECTADO:", conexao.execute(
        "PRAGMA database_list"
            ).fetchall())

    print("TOTAL DE CATEGORIAS:", conexao.execute(
        "SELECT COUNT(*) FROM CATEGORIA_PRODUTO"
            ).fetchone()[0])

    print("CATEGORIAS:", [
    dict(c) for c in conexao.execute(
        "SELECT id_categoria, nome, ativa FROM CATEGORIA_PRODUTO"
            ).fetchall()
    ])

    try:
        categorias = conexao.execute("""
        SELECT *
        FROM CATEGORIA_PRODUTO
         """).fetchall()

        print("TODAS AS CATEGORIAS:", [dict(c) for c in categorias])

        print("CATEGORIAS ENCONTRADAS:", [dict(c) for c in categorias])

        if request.method == "POST":
            nome = request.form.get("nome", "").strip()
            id_categoria = request.form.get("id_categoria")
            unidade_medida = request.form.get("unidade_medida")
            quantidade_atual = request.form.get("quantidade_atual", "0")
            controla_estoque = request.form.get("controla_estoque")
            quantidade_minima = request.form.get("quantidade_minima")

            if not nome or not id_categoria or not unidade_medida:
                flash("Preencha todos os campos obrigatórios.", "erro")
                return render_template(
                    "novo_produto.html",
                    categorias=categorias
                )

            try:
                quantidade_atual = float(
                    quantidade_atual.replace(",", ".")
                )

                if quantidade_atual < 0:
                    raise ValueError

                if quantidade_minima:
                    quantidade_minima = float(
                        quantidade_minima.replace(",", ".")
                    )
                    if quantidade_minima < 0:
                        raise ValueError
                else:
                    quantidade_minima = None

            except ValueError:
                flash("Informe quantidades válidas.", "erro")
                return render_template(
                    "novo_produto.html",
                    categorias=categorias
                )

            controla_estoque = 1 if controla_estoque == "sim" else 0

            categoria_valida = conexao.execute("""
                SELECT id_categoria
                FROM CATEGORIA_PRODUTO
                WHERE id_categoria = ? AND ativa = 1
            """, (id_categoria,)).fetchone()

            if not categoria_valida:
                flash("Selecione uma categoria válida.", "erro")
                return render_template(
                    "novo_produto.html",
                    categorias=categorias
                )

            conexao.execute("""
                INSERT INTO PRODUTO (
                    id_familia,
                    id_categoria,
                    id_usuario_criador,
                    nome,
                    unidade_medida,
                    quantidade_atual,
                    controla_estoque,
                    quantidade_minima,
                    ativo,
                    data_cadastro
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            """, (
                session["id_familia"],
                id_categoria,
                session["id_usuario"],
                nome,
                unidade_medida,
                quantidade_atual,
                controla_estoque,
                quantidade_minima
            ))

            conexao.commit()
            flash("Produto cadastrado com sucesso!", "sucesso")
            return redirect(url_for("produtos"))

        return render_template(
            "novo_produto.html",
            categorias=categorias
        )

    except sqlite3.Error:
        conexao.rollback()
        traceback.print_exc()
        flash("Ocorreu um erro ao cadastrar o produto.", "erro")
        return redirect(url_for("produtos"))

    finally:
        conexao.close()




# =========================================================
# PRODUTOS 
# =========================================================
@app.route("/produtos")
def produtos():
    if "id_usuario" not in session:
        return redirect(url_for("login"))

    conexao = conectar_banco()

    try:
        produtos = conexao.execute("""
            SELECT
                P.*,
                C.nome AS categoria
            FROM PRODUTO P
            INNER JOIN CATEGORIA_PRODUTO C
                ON P.id_categoria = C.id_categoria
            WHERE
                P.id_familia = ?
                AND P.ativo = 1
            ORDER BY P.nome
        """, (session["id_familia"],)).fetchall()

        return render_template(
            "produtos.html",
            produtos=produtos
        )

    except sqlite3.Error:
        traceback.print_exc()
        flash("Não foi possível carregar os produtos.", "erro")
        return redirect(url_for("dashboard"))

    finally:
        conexao.close()




# =========================================================
# EDITAR PRODUTO
# =========================================================
@app.route("/produtos/editar/<int:id_produto>", methods=["GET", "POST"])
def editar_produto(id_produto):
    if "id_usuario" not in session:
        return redirect(url_for("login"))

    conexao = conectar_banco()

    try:
        produto = conexao.execute("""
            SELECT *
            FROM PRODUTO
            WHERE id_produto = ?
              AND id_familia = ?
              AND ativo = 1
        """, (
            id_produto,
            session["id_familia"]
        )).fetchone()

        if not produto:
            flash("Produto não encontrado.", "erro")
            return redirect(url_for("produtos"))

        categorias = conexao.execute("""
            SELECT *
            FROM CATEGORIA_PRODUTO
            WHERE ativa = 1
            ORDER BY nome
        """).fetchall()

        if request.method == "POST":
            nome = request.form.get("nome", "").strip()
            id_categoria = request.form.get("id_categoria")
            unidade_medida = request.form.get("unidade_medida")
            quantidade_atual = request.form.get("quantidade_atual", "0")
            controla_estoque = request.form.get("controla_estoque")
            quantidade_minima = request.form.get("quantidade_minima")

            if not nome or not id_categoria or not unidade_medida:
                flash("Preencha todos os campos obrigatórios.", "erro")
            else:
                try:
                    quantidade_atual = float(
                        quantidade_atual.replace(",", ".")
                    )

                    if quantidade_atual < 0:
                        raise ValueError

                    if quantidade_minima:
                        quantidade_minima = float(
                            quantidade_minima.replace(",", ".")
                        )

                        if quantidade_minima < 0:
                            raise ValueError
                    else:
                        quantidade_minima = None

                    id_categoria = int(id_categoria)

                    categoria_valida = conexao.execute("""
                        SELECT id_categoria
                        FROM CATEGORIA_PRODUTO
                        WHERE id_categoria = ? AND ativa = 1
                    """, (id_categoria,)).fetchone()

                    if not categoria_valida:
                        raise ValueError

                    if controla_estoque not in ("sim", "nao"):
                        raise ValueError

                except ValueError:
                    flash("Verifique os dados informados.", "erro")
                else:
                    conexao.execute("""
                        UPDATE PRODUTO
                        SET
                            nome = ?,
                            id_categoria = ?,
                            unidade_medida = ?,
                            quantidade_atual = ?,
                            controla_estoque = ?,
                            quantidade_minima = ?
                        WHERE id_produto = ?
                          AND id_familia = ?
                    """, (
                        nome,
                        id_categoria,
                        unidade_medida,
                        quantidade_atual,
                        1 if controla_estoque == "sim" else 0,
                        quantidade_minima,
                        id_produto,
                        session["id_familia"]
                    ))

                    conexao.commit()
                    flash("Produto atualizado com sucesso!", "sucesso")
                    return redirect(url_for("produtos"))

        return render_template(
            "editar_produto.html",
            produto=produto,
            categorias=categorias
        )

    except sqlite3.Error:
        conexao.rollback()
        traceback.print_exc()
        flash("Não foi possível atualizar o produto.", "erro")
        return redirect(url_for("produtos"))

    finally:
        conexao.close()




# =========================================================
# DESATIVAR PRODUTO
# =========================================================
@app.route("/produtos/desativar/<int:id_produto>", methods=["POST"])
def desativar_produto(id_produto):
    if "id_usuario" not in session:
        return redirect(url_for("login"))

    conexao = conectar_banco()

    try:
        produto = conexao.execute("""
            SELECT id_produto
            FROM PRODUTO
            WHERE id_produto = ?
              AND id_familia = ?
              AND ativo = 1
        """, (
            id_produto,
            session["id_familia"]
        )).fetchone()

        if not produto:
            flash("Produto não encontrado.", "erro")
            return redirect(url_for("produtos"))

        conexao.execute("""
            UPDATE PRODUTO
            SET ativo = 0
            WHERE id_produto = ?
              AND id_familia = ?
        """, (
            id_produto,
            session["id_familia"]
        ))

        conexao.commit()

        flash("Produto desativado com sucesso!", "sucesso")

    except sqlite3.Error:
        conexao.rollback()
        traceback.print_exc()
        flash("Não foi possível desativar o produto.", "erro")

    finally:
        conexao.close()

    return redirect(url_for("produtos"))




# =========================================================
# MERCADO
# =========================================================
@app.route("/mercado", methods=["GET", "POST"])
def mercado():
    if "id_usuario" not in session:
        return redirect(url_for("login"))

    conexao = conectar_banco()

    try:
        if request.method == "POST":
            nome = request.form.get("nome", "").strip()
            quantidade = request.form.get("quantidade", "").strip()
            unidade_medida = request.form.get("unidade_medida", "").strip()

            if not nome or not quantidade:
                flash("Informe o nome e a quantidade do produto.", "erro")
            else:
                try:
                    quantidade = float(quantidade.replace(",", "."))

                    if quantidade <= 0:
                        raise ValueError

                except ValueError:
                    flash("Informe uma quantidade válida.", "erro")
                else:
                    conexao.execute("""
                        INSERT INTO ITEM_MERCADO (
                            id_familia,
                            id_produto,
                            id_usuario,
                            quantidade,
                            status,
                            data_adicao,
                            data_compra,
                            nome_produto,
                            unidade_medida
                        )
                        VALUES (?, NULL, ?, ?, 'PENDENTE',
                                CURRENT_TIMESTAMP, NULL, ?, ?)
                    """, (
                        session["id_familia"],
                        session["id_usuario"],
                        quantidade,
                        nome,
                        unidade_medida if unidade_medida else None
                    ))

                    conexao.commit()

                    flash("Produto adicionado à lista!", "sucesso")
                    return redirect(url_for("mercado"))

        itens_pendentes = conexao.execute("""
            SELECT *
            FROM ITEM_MERCADO
            WHERE id_familia = ?
              AND status = 'PENDENTE'
            ORDER BY data_adicao DESC
        """, (session["id_familia"],)).fetchall()

        return render_template(
            "mercado.html",
            itens_pendentes=itens_pendentes
        )

    except sqlite3.Error:
        conexao.rollback()
        traceback.print_exc()
        flash("Não foi possível carregar a lista de mercado.", "erro")
        return redirect(url_for("dashboard"))

    finally:
        conexao.close()



# =========================================================
# MERCADO COMPRADO
# =========================================================
@app.route("/mercado/comprado/<int:id_item>", methods=["POST"])
def marcar_comprado(id_item):
    if "id_usuario" not in session:
        return redirect(url_for("login"))

    conexao = conectar_banco()

    try:
        item = conexao.execute("""
            SELECT id_item
            FROM ITEM_MERCADO
            WHERE id_item = ?
              AND id_familia = ?
              AND status = 'PENDENTE'
        """, (
            id_item,
            session["id_familia"]
        )).fetchone()

        if not item:
            flash("Item não encontrado na lista.", "erro")
        else:
            conexao.execute("""
                UPDATE ITEM_MERCADO
                SET status = 'COMPRADO',
                    data_compra = CURRENT_TIMESTAMP
                WHERE id_item = ?
                  AND id_familia = ?
            """, (
                id_item,
                session["id_familia"]
            ))

            conexao.commit()
            flash("Produto marcado como comprado!", "sucesso")

    except sqlite3.Error:
        conexao.rollback()
        traceback.print_exc()
        flash("Não foi possível atualizar o item.", "erro")

    finally:
        conexao.close()

    return redirect(url_for("mercado"))




# =========================================================
# ESTOQUE
# =========================================================
@app.route("/estoque")
def estoque():

    if "id_usuario" not in session:
        return redirect(url_for("login"))

    conexao = conectar_banco()

    try:

        produtos = conexao.execute("""
            SELECT
                id_produto,
                nome,
                unidade_medida,
                quantidade_atual,
                quantidade_minima
            FROM PRODUTO
            WHERE id_familia = ?
              AND controla_estoque = 1
              AND ativo = 1
            ORDER BY nome
        """, (session["id_familia"],)).fetchall()

        total_produtos = len(produtos)

        produtos_baixos = [
            p for p in produtos
            if p["quantidade_minima"] is not None
            and p["quantidade_atual"] <= p["quantidade_minima"]
        ]

        total_baixos = len(produtos_baixos)
        total_normais = total_produtos - total_baixos

        return render_template(
            "estoque.html",
            produtos=produtos,
            total_produtos=total_produtos,
            total_baixos=total_baixos,
            total_normais=total_normais
        )

    except sqlite3.Error as erro:

        traceback.print_exc()
        flash("Não foi possível carregar o estoque.")

        return redirect(url_for("dashboard"))

    finally:
        conexao.close()


# =========================================================
# REGISTRAR ENTRADA OU SAÍDA DO ESTOQUE
# =========================================================

@app.route(
    "/estoque/movimentar/<int:id_produto>",
    methods=["POST"]
)
def movimentar_estoque(id_produto):

    if "id_usuario" not in session:
        return redirect(url_for("login"))

    tipo = request.form.get("tipo", "").upper()
    quantidade = request.form.get("quantidade", "").strip()
    observacao = request.form.get("observacao", "").strip()

    if tipo not in ("ENTRADA", "SAIDA"):
        flash("Tipo de movimentação inválido.")
        return redirect(url_for("estoque"))

    try:
        quantidade = float(quantidade.replace(",", "."))

        if quantidade <= 0:
            raise ValueError

    except ValueError:
        flash("Informe uma quantidade válida.")
        return redirect(url_for("estoque"))

    conexao = conectar_banco()

    try:

        produto = conexao.execute("""
            SELECT *
            FROM PRODUTO
            WHERE id_produto = ?
              AND id_familia = ?
              AND controla_estoque = 1
              AND ativo = 1
        """, (
            id_produto,
            session["id_familia"]
        )).fetchone()

        if not produto:
            flash("Produto não encontrado no estoque.")
            return redirect(url_for("estoque"))

        quantidade_atual = float(produto["quantidade_atual"])

        if tipo == "ENTRADA":
            nova_quantidade = quantidade_atual + quantidade

        else:
            if quantidade > quantidade_atual:
                flash("A quantidade de saída é maior que o estoque disponível.")
                return redirect(url_for("estoque"))

            nova_quantidade = quantidade_atual - quantidade

        conexao.execute("""
            UPDATE PRODUTO
            SET quantidade_atual = ?
            WHERE id_produto = ?
              AND id_familia = ?
        """, (
            nova_quantidade,
            id_produto,
            session["id_familia"]
        ))

        conexao.execute("""
            INSERT INTO MOVIMENTACAO_ESTOQUE (
                id_familia,
                id_produto,
                id_usuario,
                tipo,
                quantidade,
                data_movimentacao,
                observacao
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
        """, (
            session["id_familia"],
            id_produto,
            session["id_usuario"],
            tipo,
            quantidade,
            observacao if observacao else None
        ))

        conexao.commit()

        flash("Movimentação registrada com sucesso!")

    except sqlite3.Error:

        conexao.rollback()
        traceback.print_exc()

        flash("Não foi possível registrar a movimentação.")

    finally:
        conexao.close()

    return redirect(url_for("estoque"))




# =========================================================
# HISTÓRICO DE MOVIMENTAÇÕES DO ESTOQUE
# =========================================================
@app.route("/estoque/historico")
def historico_estoque():

    if "id_usuario" not in session:
        return redirect(url_for("login"))

    conexao = conectar_banco()

    try:

        movimentacoes = conexao.execute("""
            SELECT
                M.id_movimentacao,
                M.tipo,
                M.quantidade,
                M.data_movimentacao,
                M.observacao,
                P.nome AS nome_produto,
                P.unidade_medida,
                U.nome AS nome_usuario

            FROM MOVIMENTACAO_ESTOQUE M

            INNER JOIN PRODUTO P
                ON M.id_produto = P.id_produto

            INNER JOIN USUARIO U
                ON M.id_usuario = U.id_usuario

            WHERE M.id_familia = ?

            ORDER BY M.data_movimentacao DESC,
                     M.id_movimentacao DESC

        """, (session["id_familia"],)).fetchall()

        return render_template(
            "historico_estoque.html",
            movimentacoes=movimentacoes
        )

    except sqlite3.Error:

        traceback.print_exc()
        flash("Não foi possível carregar o histórico.")

        return redirect(url_for("estoque"))

    finally:
        conexao.close()





# =========================================================
# AJUSTAR ESTOQUE
# =========================================================
@app.route("/estoque/ajustar/<int:id_produto>", methods=["POST"])
def ajustar_estoque(id_produto):

    if "id_usuario" not in session:
        return redirect(url_for("login"))

    quantidade = request.form.get("quantidade", "").strip()
    observacao = request.form.get("observacao", "").strip()

    try:
        nova_quantidade = float(quantidade.replace(",", "."))

        if nova_quantidade < 0:
            raise ValueError

    except ValueError:
        flash("Informe uma quantidade válida.")
        return redirect(url_for("estoque"))

    conexao = conectar_banco()

    try:

        produto = conexao.execute("""
            SELECT *
            FROM PRODUTO
            WHERE id_produto = ?
              AND id_familia = ?
              AND controla_estoque = 1
              AND ativo = 1
        """, (
            id_produto,
            session["id_familia"]
        )).fetchone()

        if not produto:
            flash("Produto não encontrado no estoque.")
            return redirect(url_for("estoque"))

        quantidade_anterior = float(produto["quantidade_atual"])

        if nova_quantidade == quantidade_anterior:
            flash("A quantidade informada já é a quantidade atual.")
            return redirect(url_for("estoque"))

        diferenca = abs(nova_quantidade - quantidade_anterior)

        conexao.execute("""
            UPDATE PRODUTO
            SET quantidade_atual = ?
            WHERE id_produto = ?
              AND id_familia = ?
        """, (
            nova_quantidade,
            id_produto,
            session["id_familia"]
        ))

        descricao = (
            f"Quantidade ajustada de {quantidade_anterior} "
            f"para {nova_quantidade}."
        )

        if observacao:
            descricao += f" Observação: {observacao}"

        conexao.execute("""
            INSERT INTO MOVIMENTACAO_ESTOQUE (
                id_familia,
                id_produto,
                id_usuario,
                tipo,
                quantidade,
                data_movimentacao,
                observacao
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
        """, (
            session["id_familia"],
            id_produto,
            session["id_usuario"],
            "AJUSTE",
            diferenca,
            descricao
        ))

        conexao.commit()

        flash("Estoque ajustado com sucesso!")

    except sqlite3.Error:

        conexao.rollback()
        traceback.print_exc()

        flash("Não foi possível ajustar o estoque.")

    finally:
        conexao.close()

    return redirect(url_for("estoque"))




# =========================================================
# DASHBOARD
# =========================================================
@app.route("/dashboard")
def dashboard():

    if "id_usuario" not in session:
        return redirect(url_for("login"))

    return render_template("dashboard.html")


# =========================================================
# LOGOUT
# =========================================================
@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# =========================================================
# EXECUTAR APLICAÇÃO
# =========================================================
if __name__ == "__main__":
    app.run(debug=True)