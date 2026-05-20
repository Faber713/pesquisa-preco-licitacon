from collectors.pncp.normalizer import agora_iso


def obter_checkpoint(con, endpoint, data_inicial, data_final):
    return con.execute(
        """
        SELECT *
        FROM pncp_coleta_checkpoint
        WHERE endpoint = ? AND data_inicial = ? AND data_final = ?
        LIMIT 1
        """,
        (endpoint, data_inicial, data_final),
    ).fetchone()


def salvar_checkpoint(
    con,
    *,
    endpoint,
    data_inicial,
    data_final,
    pagina_atual,
    total_paginas,
    status,
):
    con.execute(
        """
        INSERT INTO pncp_coleta_checkpoint
        (endpoint, data_inicial, data_final, pagina_atual, total_paginas, status, atualizado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(endpoint, data_inicial, data_final)
        DO UPDATE SET
            pagina_atual = excluded.pagina_atual,
            total_paginas = excluded.total_paginas,
            status = excluded.status,
            atualizado_em = excluded.atualizado_em
        """,
        (
            endpoint,
            data_inicial,
            data_final,
            int(pagina_atual or 0),
            int(total_paginas or 0),
            status,
            agora_iso(),
        ),
    )
    con.commit()


def registrar_log_coleta(
    con,
    *,
    endpoint,
    pagina,
    status_code=0,
    tempo_ms=0,
    retries=0,
    mensagem="",
):
    con.execute(
        """
        INSERT INTO pncp_coleta_logs
        (timestamp, endpoint, pagina, status_code, tempo_ms, retries, mensagem)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            agora_iso(),
            endpoint,
            int(pagina or 0),
            int(status_code or 0),
            float(tempo_ms or 0),
            int(retries or 0),
            mensagem,
        ),
    )
    con.commit()

