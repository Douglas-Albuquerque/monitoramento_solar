import os
from datetime import datetime
import json
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from werkzeug.security import check_password_hash, generate_password_hash

from flask import Flask, render_template
from dotenv import load_dotenv
import mysql.connector

# Carrega o mesmo .env da raiz
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

app = Flask(__name__)

# Por enquanto, uma chave simples (depois colocamos no .env)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "mude-esta-chave")

login_manager = LoginManager(app)
login_manager.login_view = "login"


class User(UserMixin):
    def __init__(self, id, username, senha_hash, ativo):
        self.id = id
        self.username = username
        self.senha_hash = senha_hash
        self.ativo = bool(ativo)

    @staticmethod
    def get_by_username(username):
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, username, senha_hash, ativo FROM usuarios WHERE username = %s",
            (username,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None
        return User(row["id"], row["username"], row["senha_hash"], row["ativo"])

    @staticmethod
    def get_by_id(user_id):
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, username, senha_hash, ativo FROM usuarios WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None
        return User(row["id"], row["username"], row["senha_hash"], row["ativo"])


@login_manager.user_loader
def load_user(user_id):
    return User.get_by_id(user_id)


def get_db_connection():
    """
    Usa o MESMO banco do sistema principal.
    """
    return mysql.connector.connect(
        unix_socket="/var/run/mysqld/mysqld.sock",
        user=os.getenv("DB_USER", "solar_user"),
        password=os.getenv("DB_PASS", ""),
        database=os.getenv("DB_NAME", "solar_monitor"),
    )


from datetime import time, timedelta  # já vamos usar depois


def recortar_para_horario_sol(inicio, fim):
    """
    Recorta o intervalo [inicio, fim] para dentro da janela de sol (06:00–18:00).
    Se não houver interseção, retorna None.
    """
    inicio_sol = inicio.replace(hour=6, minute=0, second=0, microsecond=0)
    fim_sol = fim.replace(hour=18, minute=0, second=0, microsecond=0)

    inicio_aj = max(inicio, inicio_sol)
    fim_aj = min(fim, fim_sol)

    if fim_aj <= inicio_aj:
        return None

    return {
        "inicio": inicio_aj,
        "fim": fim_aj,
    }


def intervalo_ja_registrado(nome_usina, inicio, fim):
    """
    Verifica se já existe uma parada registrada que cobre esse intervalo.
    Critério simples: qualquer parada da mesma usina que tenha
    interseção significativa com [inicio, fim].
    """
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT 1
        FROM paradas_usinas
        WHERE nome_usina = %s
          AND NOT (fim <= %s OR inicio >= %s)
        LIMIT 1
        """,
        (nome_usina, inicio, fim),
    )
    existe = cur.fetchone() is not None
    cur.close()
    conn.close()
    return existe


def obter_intervalos_parada(nome_usina, data_inicio, data_fim):
    """
    Lê o histórico no período e devolve intervalos de parada
    (OFFLINE/ERRO) já recortados para dentro do horário de sol (06:00–18:00),
    ignorando intervalos que já tenham uma parada registrada.

    CASO ESPECIAL:
      - Para 'UFV CASA 4', usa o campo mensagem='Placa X' para sugerir paradas
        por placa, com nome_usina = 'UFV CASA 4 - <codigo_placa>'.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    intervalos = []

    # Caso especial: UFV CASA 4 por placa
    if nome_usina == "UFV CASA 4":
        cur.execute(
            """
            SELECT nome_usina, status, changed_at, mensagem
            FROM usinas_status_historico
            WHERE nome_usina = %s
              AND changed_at BETWEEN %s AND %s
              AND mensagem LIKE 'Placa %%'
            ORDER BY changed_at
            """,
            (nome_usina, data_inicio, data_fim),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        # agrupa por código de placa extraído de mensagem ("Placa 4139...")
        por_placa = {}
        for row in rows:
            msg = row.get("mensagem") or ""
            partes = msg.split()
            codigo = partes[1] if len(partes) >= 2 else None
            if not codigo:
                continue
            if codigo not in por_placa:
                por_placa[codigo] = []
            por_placa[codigo].append(
                {
                    "status": row["status"],
                    "changed_at": row["changed_at"],
                }
            )

        for codigo, rows_placa in por_placa.items():
            rows_placa.sort(key=lambda r: r["changed_at"])
            em_parada = False
            inicio_parada = None
            nome_parada = f"{nome_usina} - {codigo}"

            def adiciona_intervalo_bruto_placa(inicio, fim):
                intervalo_aj = recortar_para_horario_sol(inicio, fim)
                if intervalo_aj is None:
                    return
                if intervalo_ja_registrado(
                    nome_parada, intervalo_aj["inicio"], intervalo_aj["fim"]
                ):
                    return
                intervalos.append(
                    {
                        "nome_usina": nome_parada,
                        "inicio": intervalo_aj["inicio"],
                        "fim": intervalo_aj["fim"],
                    }
                )

            for r in rows_placa:
                status = r["status"]
                ts = r["changed_at"]

                if not em_parada and status in ("OFFLINE", "ERRO"):
                    em_parada = True
                    inicio_parada = ts
                elif em_parada and status == "ONLINE":
                    fim_parada = ts
                    adiciona_intervalo_bruto_placa(inicio_parada, fim_parada)
                    em_parada = False
                    inicio_parada = None

            # mesma regra do seu código original:
            # se ainda está em OFFLINE/ERRO e não voltou, não sugere (parada em andamento)
            # então não fechamos com data_fim aqui

        return intervalos

    # Caso padrão (todas as outras usinas) - mesma lógica que você já tinha
    cur.execute(
        """
        SELECT nome_usina, status, changed_at
        FROM usinas_status_historico
        WHERE nome_usina = %s
          AND changed_at BETWEEN %s AND %s
        ORDER BY changed_at
        """,
        (nome_usina, data_inicio, data_fim),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    em_parada = False
    inicio_parada = None

    def adiciona_intervalo_bruto(inicio, fim):
        intervalo_aj = recortar_para_horario_sol(inicio, fim)
        if intervalo_aj is None:
            return
        # Se já existe parada registrada nesse intervalo, não sugerir de novo
        if intervalo_ja_registrado(
            nome_usina, intervalo_aj["inicio"], intervalo_aj["fim"]
        ):
            return
        intervalos.append(
            {
                "nome_usina": nome_usina,
                "inicio": intervalo_aj["inicio"],
                "fim": intervalo_aj["fim"],
            }
        )

    for row in rows:
        status = row["status"]
        ts = row["changed_at"]

        if not em_parada and status in ("OFFLINE", "ERRO"):
            em_parada = True
            inicio_parada = ts
        elif em_parada and status == "ONLINE":
            fim_parada = ts
            adiciona_intervalo_bruto(inicio_parada, fim_parada)
            em_parada = False
            inicio_parada = None

    # NÃO fecha paradas abertas; se ainda está em OFFLINE/ERRO e não voltou,
    # consideramos que a parada está em andamento e não mostramos na tela.

    return intervalos


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        senha = request.form.get("senha", "")

        user = User.get_by_username(username)
        if (
            not user
            or not user.ativo
            or not check_password_hash(user.senha_hash, senha)
        ):
            flash("Usuário ou senha inválidos.", "danger")
            return redirect(url_for("login"))

        login_user(user)
        flash("Login realizado com sucesso.", "success")
        next_page = request.args.get("next") or url_for("home")
        return redirect(next_page)

    return render_template("login.html")


@app.route("/relatorio-mensal")
@login_required
def relatorio_mensal():
    # filtros simples: mês/ano e, opcionalmente, usina
    ano = request.args.get("ano", type=int)
    mes = request.args.get("mes", type=int)
    usina_sel = request.args.get("usina")

    hoje = datetime.today().date()
    if not ano:
        ano = hoje.year
    if not mes:
        mes = hoje.month

    # início/fim do mês
    data_inicio = datetime(ano, mes, 1)
    if mes == 12:
        data_fim = datetime(ano + 1, 1, 1) - timedelta(seconds=1)
    else:
        data_fim = datetime(ano, mes + 1, 1) - timedelta(seconds=1)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    # lista de usinas para filtro
    cur.execute("SELECT DISTINCT nome_usina FROM paradas_usinas ORDER BY nome_usina")
    usinas = [row["nome_usina"] for row in cur.fetchall()]

    # motivos para o select do modal
    cur.execute(
        "SELECT id, descricao FROM motivos_parada WHERE ativo = 1 ORDER BY descricao"
    )
    motivos = cur.fetchall()

    params = [data_inicio, data_fim]
    where_usina = ""
    if usina_sel:
        where_usina = "AND p.nome_usina = %s"
        params.append(usina_sel)

    # RESUMO por usina/motivo
    cur.execute(
        f"""
        SELECT
          p.nome_usina,
          m.descricao AS motivo,
          SUM(TIMESTAMPDIFF(MINUTE, p.inicio, p.fim)) AS minutos_total,
          COUNT(*) AS qtde_paradas
        FROM paradas_usinas p
        JOIN motivos_parada m ON m.id = p.motivo_id
        WHERE p.inicio BETWEEN %s AND %s
          {where_usina}
        GROUP BY p.nome_usina, m.descricao
        ORDER BY p.nome_usina, minutos_total DESC
        """,
        params,
    )
    linhas = cur.fetchall()

    # DETALHES por parada (para edição)
    cur.execute(
        f"""
        SELECT
          p.id,
          p.nome_usina,
          p.inicio,
          p.fim,
          m.descricao AS motivo,
          p.motivo_id,
          p.observacao
        FROM paradas_usinas p
        JOIN motivos_parada m ON m.id = p.motivo_id
        WHERE p.inicio BETWEEN %s AND %s
          {where_usina}
        ORDER BY p.nome_usina, p.inicio
        """,
        params,
    )
    paradas_detalhe = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "relatorio_mensal.html",
        usuario=current_user.username,
        ano=ano,
        mes=mes,
        usinas=usinas,
        usina_sel=usina_sel,
        linhas=linhas,
        paradas_detalhe=paradas_detalhe,
        inicio_mes=data_inicio,
        fim_mes=data_fim,
        motivos_todos=motivos,
    )


@app.route("/paradas/editar", methods=["POST"])
@login_required
def editar_parada():
    parada_id = request.form.get("id")
    motivo_id = request.form.get("motivo_id")
    observacao = request.form.get("observacao", "").strip()

    if not parada_id or not motivo_id:
        flash("Dados incompletos para editar a parada.", "danger")
        return redirect(url_for("relatorio_mensal"))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE paradas_usinas
        SET motivo_id = %s,
            observacao = %s
        WHERE id = %s
        """,
        (int(motivo_id), observacao or None, int(parada_id)),
    )
    conn.commit()
    cur.close()
    conn.close()

    flash("Parada atualizada com sucesso.", "success")
    return redirect(
        url_for(
            "relatorio_mensal",
            ano=request.args.get("ano"),
            mes=request.args.get("mes"),
            usina=request.args.get("usina"),
        )
    )


@app.route("/relatorio-reincidencia")
@login_required
def relatorio_reincidencia():
    # permite filtrar a partir de um mês/ano, mas sempre olha 3 meses para trás
    ano = request.args.get("ano", type=int)
    mes = request.args.get("mes", type=int)
    usina_sel = request.args.get("usina")

    hoje = datetime.today().date()
    if not ano:
        ano = hoje.year
    if not mes:
        mes = hoje.month

    # fim = último dia do mês informado, início = 3 meses atrás
    fim_mes = datetime(ano, mes, 1)
    if mes == 12:
        fim_mes = datetime(ano + 1, 1, 1) - timedelta(seconds=1)
    else:
        fim_mes = datetime(ano, mes + 1, 1) - timedelta(seconds=1)

    # início: 3 meses antes
    if mes <= 3:
        ano_ini = ano - 1
        mes_ini = mes + 9
    else:
        ano_ini = ano
        mes_ini = mes - 3
    inicio_mes = datetime(ano_ini, mes_ini, 1)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    # usinas com paradas para filtro
    cur.execute("SELECT DISTINCT nome_usina FROM paradas_usinas ORDER BY nome_usina")
    usinas = [row["nome_usina"] for row in cur.fetchall()]

    params = [inicio_mes, fim_mes]
    where_usina = ""
    if usina_sel:
        where_usina = "AND p.nome_usina = %s"
        params.append(usina_sel)

    # agrupa por motivo (e usina) contando quantas paradas em 3 meses
    cur.execute(
        f"""
        SELECT
            p.nome_usina,
            m.descricao AS motivo,
            COUNT(*) AS qtde_paradas,
            SUM(TIMESTAMPDIFF(MINUTE, p.inicio, p.fim)) AS minutos_total
        FROM paradas_usinas p
        JOIN motivos_parada m ON m.id = p.motivo_id
        WHERE p.inicio BETWEEN %s AND %s
          {where_usina}
        GROUP BY p.nome_usina, m.descricao
        ORDER BY qtde_paradas DESC, minutos_total DESC
        """,
        params,
    )
    linhas = cur.fetchall()
    cur.close()
    conn.close()

    return render_template(
        "relatorio_reincidencia.html",
        usuario=current_user.username,
        ano=ano,
        mes=mes,
        usinas=usinas,
        usina_sel=usina_sel,
        inicio_mes=inicio_mes,
        fim_mes=fim_mes,
        linhas=linhas,
    )


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Você saiu do sistema.", "info")
    return redirect(url_for("login"))


from datetime import date


@app.route("/home")
@login_required
def home():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    # total de paradas hoje
    cur.execute(
        """
        SELECT COUNT(*) AS total
        FROM paradas_usinas
        WHERE DATE(inicio) = CURDATE()
    """
    )
    row = cur.fetchone()
    total_paradas_hoje = row["total"] if row else 0

    # total de paradas e horas de parada no mês atual
    cur.execute(
        """
        SELECT
          COUNT(*) AS total_paradas,
          SUM(TIMESTAMPDIFF(MINUTE, inicio, fim)) / 60 AS horas_paradas
        FROM paradas_usinas
        WHERE YEAR(inicio) = YEAR(CURDATE())
          AND MONTH(inicio) = MONTH(CURDATE())
    """
    )
    row = cur.fetchone() or {}
    total_paradas_mes = row.get("total_paradas", 0) or 0
    horas_paradas_mes = row.get("horas_paradas", 0) or 0

    # usina com mais paradas no mês
    cur.execute(
        """
        SELECT nome_usina AS usina, COUNT(*) AS qtd
        FROM paradas_usinas
        WHERE YEAR(inicio) = YEAR(CURDATE())
          AND MONTH(inicio) = MONTH(CURDATE())
        GROUP BY nome_usina
        ORDER BY qtd DESC
        LIMIT 1
    """
    )
    row = cur.fetchone()
    usina_top_nome = row["usina"] if row else None
    usina_top_qtd = row["qtd"] if row else None

    cur.execute(
        """
    SELECT DAY(inicio) AS dia, COUNT(*) AS qtde
    FROM paradas_usinas
    WHERE YEAR(inicio) = YEAR(CURDATE())
      AND MONTH(inicio) = MONTH(CURDATE())
    GROUP BY DAY(inicio)
    ORDER BY dia
"""
    )
    rows = cur.fetchall()
    dias_labels = [str(r["dia"]) for r in rows]
    dias_values = [r["qtde"] for r in rows]

    # paradas por motivo (mês atual)
    cur.execute(
        """
        SELECT m.descricao AS motivo, COUNT(*) AS qtde
        FROM paradas_usinas p
        JOIN motivos_parada m ON m.id = p.motivo_id
        WHERE YEAR(p.inicio) = YEAR(CURDATE())
        AND MONTH(p.inicio) = MONTH(CURDATE())
        GROUP BY m.descricao
        ORDER BY qtde DESC
    """
    )
    rows = cur.fetchall()
    motivos_labels = [r["motivo"] for r in rows]
    motivos_values = [r["qtde"] for r in rows]

    cur.execute(
        """
    SELECT nome_usina AS usina, COUNT(*) AS qtde
    FROM paradas_usinas
    WHERE YEAR(inicio) = YEAR(CURDATE())
      AND MONTH(inicio) = MONTH(CURDATE())
    GROUP BY nome_usina
    ORDER BY qtde DESC
    """
    )
    rows = cur.fetchall()
    usinas_labels = [r["usina"] for r in rows]
    usinas_values = [r["qtde"] for r in rows]

    cur.close()
    conn.close()

    hoje = date.today()
    meses = [
        "",
        "Janeiro",
        "Fevereiro",
        "Março",
        "Abril",
        "Maio",
        "Junho",
        "Julho",
        "Agosto",
        "Setembro",
        "Outubro",
        "Novembro",
        "Dezembro",
    ]

    return render_template(
        "home.html",
        total_paradas_hoje=total_paradas_hoje,
        total_paradas_mes=total_paradas_mes,
        horas_paradas_mes=horas_paradas_mes,
        usina_top_nome=usina_top_nome,
        usina_top_qtd=usina_top_qtd,
        ano_referencia=hoje.year,
        mes_referencia=hoje.month,
        mes_referencia_str=meses[hoje.month],
        data_hoje_str=hoje.strftime("%d/%m/%Y"),
        dias_labels=json.dumps(dias_labels, ensure_ascii=False),
        dias_values=json.dumps(dias_values),
        motivos_labels=json.dumps(motivos_labels, ensure_ascii=False),
        motivos_values=json.dumps(motivos_values),
        usinas_labels=json.dumps(usinas_labels, ensure_ascii=False),
        usinas_values=json.dumps(usinas_values),
    )


from datetime import datetime, timedelta

from datetime import (
    datetime,
    timedelta,
)  # se ainda não estiver no topo, já está lá em cima


@app.route("/motivos/editar", methods=["POST"])
@login_required
def editar_motivo():
    motivo_id = request.form.get("id")
    descricao = request.form.get("descricao", "").strip()

    if not descricao:
        flash("Descrição não pode ser vazia.", "danger")
        return redirect(url_for("motivos"))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE motivos_parada SET descricao = %s WHERE id = %s",
        (descricao, motivo_id),
    )
    conn.commit()
    cur.close()
    conn.close()

    flash("Motivo atualizado com sucesso.", "success")
    return redirect(url_for("motivos"))


@app.route("/paradas", methods=["GET", "POST"])
@login_required
def paradas():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    # Usinas distintas (histórico geral)
    cur.execute(
        "SELECT DISTINCT nome_usina FROM usinas_status_historico ORDER BY nome_usina"
    )
    usinas = [row["nome_usina"] for row in cur.fetchall()]

    # Motivos ativos
    cur.execute(
        "SELECT id, descricao FROM motivos_parada WHERE ativo = 1 ORDER BY descricao"
    )
    motivos = cur.fetchall()

    if request.method == "POST":
        nome_usina = request.form.get("nome_usina")
        inicio_str = request.form.get("inicio")
        fim_str = request.form.get("fim")
        motivo_id = request.form.get("motivo_id")
        observacao = request.form.get("observacao", "").strip()

        try:
            inicio_dt = datetime.fromisoformat(inicio_str)
            fim_dt = datetime.fromisoformat(fim_str)
        except Exception:
            flash("Erro ao interpretar datas da parada.", "danger")
        else:
            cur2 = conn.cursor()
            cur2.execute(
                """
                INSERT INTO paradas_usinas
                    (nome_usina, motivo_id, inicio, fim, observacao, criado_por)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    nome_usina,
                    int(motivo_id),
                    inicio_dt,
                    fim_dt,
                    observacao or None,
                    int(current_user.id),
                ),
            )
            conn.commit()
            cur2.close()
            flash("Parada registrada com sucesso.", "success")

        # redireciona para limpar POST e manter filtros atuais
        return redirect(
            url_for(
                "paradas",
                data_inicio=request.args.get("data_inicio"),
                data_fim=request.args.get("data_fim"),
            )
        )

    cur.close()
    conn.close()

    # Filtros
    usina_sel = request.args.get("usina")  # None ou "" = todas
    data_inicio_str = request.args.get("data_inicio")
    data_fim_str = request.args.get("data_fim")

    hoje = datetime.today().date()
    if not data_inicio_str:
        data_inicio = datetime.combine(hoje.replace(day=1), datetime.min.time())
        data_inicio_str = data_inicio.date().isoformat()
    else:
        data_inicio = datetime.fromisoformat(data_inicio_str)

    if not data_fim_str:
        primeiro_mes_seguinte = (hoje.replace(day=1) + timedelta(days=32)).replace(
            day=1
        )
        data_fim = datetime.combine(
            primeiro_mes_seguinte - timedelta(days=1),
            datetime.max.time(),
        )
        data_fim_str = data_fim.date().isoformat()
    else:
        data_fim = datetime.fromisoformat(data_fim_str)
        data_fim = datetime.combine(data_fim, datetime.max.time())

    intervalos = []

    if usina_sel:
        # só uma usina
        intervalos = obter_intervalos_parada(usina_sel, data_inicio, data_fim)
    else:
        # todas as usinas: concatenar intervalos
        for u in usinas:
            ints = obter_intervalos_parada(u, data_inicio, data_fim)
            intervalos.extend(ints)
        # ordenar por início
        intervalos.sort(key=lambda x: x["inicio"])

    return render_template(
        "paradas.html",
        usuario=current_user.username,
        usinas=usinas,
        motivos=motivos,
        usina_sel=usina_sel,
        data_inicio_str=data_inicio_str,
        data_fim_str=data_fim_str,
        intervalos=intervalos,
    )


@app.route("/motivos", methods=["GET", "POST"])
@login_required
def motivos():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    # Se for POST, estamos criando um novo motivo
    if request.method == "POST":
        descricao = request.form.get("descricao", "").strip()
        if descricao:
            cur.execute(
                "INSERT INTO motivos_parada (descricao, ativo) VALUES (%s, 1)",
                (descricao,),
            )
            conn.commit()
            flash("Motivo de parada cadastrado com sucesso.", "success")
        else:
            flash("Descrição não pode ser vazia.", "danger")
        cur.close()
        conn.close()
        return redirect(url_for("motivos"))

    # GET: listar todos os motivos
    cur.execute("SELECT id, descricao, ativo FROM motivos_parada ORDER BY descricao")
    motivos = cur.fetchall()
    cur.close()
    conn.close()

    return render_template(
        "motivos.html",
        motivos=motivos,
        usuario=current_user.username,
    )


@app.route("/motivos/<int:motivo_id>/toggle", methods=["POST"])
@login_required
def toggle_motivo(motivo_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE motivos_parada SET ativo = 1 - ativo WHERE id = %s",
        (motivo_id,),
    )
    conn.commit()
    cur.close()
    conn.close()
    flash("Status do motivo atualizado.", "info")
    return redirect(url_for("motivos"))


if __name__ == "__main__":
    # Roda em porta 5001 para não conflitar com a dashboard
    app.run(host="0.0.0.0", port=5001, debug=True)
