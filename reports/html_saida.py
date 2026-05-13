from html import escape
from utils.config import MAX_RESULTADOS, LINK_BASE_LICITACON
from utils.util import formatar_moeda_br, formatar_percentual, preparar_js


def salvar_html(descricao_busca, qtd_min, qtd_max, criterios, resultados, nome_base):
    nome_arquivo = f"{nome_base}.html"

    descricao_link = criterios.get("descricao_sugerida_licitacon", "")
    if not descricao_link:
        descricao_link = criterios.get("descricao_resumida", descricao_busca)

    with open(nome_arquivo, "w", encoding="utf-8") as f:

        f.write("""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Pesquisa LicitaCon</title>

<style>
body {
    font-family: Arial, sans-serif;
    background: #f4f6f8;
    margin: 30px;
    color: #222;
}

h1 {
    color: #1f3a5f;
}

.resumo {
    background: white;
    padding: 18px;
    border-radius: 10px;
    margin-bottom: 20px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.10);
}

.card {
    background: white;
    border-radius: 10px;
    padding: 18px;
    margin-bottom: 18px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.10);
}

.card-amplo {
    border-left: 8px solid #f59e0b;
    background: #fffaf0;
}

.card-qtd-fora {
    border-right: 8px solid #ef4444;
}

.score {
    font-size: 20px;
    font-weight: bold;
    color: #0b6b3a;
}

.baixo {
    color: #b45309;
}

.modo-tag {
    display: inline-block;
    padding: 5px 10px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: bold;
    margin-top: 6px;
}

.modo-rigido { background: #dcfce7; color: #166534; }
.modo-relaxado { background: #dbeafe; color: #1e40af; }
.modo-amplo { background: #fef3c7; color: #92400e; }

.botao {
    display: inline-block;
    background: #1f6feb;
    color: white;
    padding: 10px 16px;
    border-radius: 8px;
    text-decoration: none;
    font-weight: bold;
    margin-top: 10px;
}

.copy-btn {
    margin-left: 8px;
    padding: 4px 8px;
    border: 1px solid #c7d2fe;
    background: #eef2ff;
    border-radius: 6px;
    cursor: pointer;
    font-size: 12px;
}

.copy-all-btn {
    margin-top: 10px;
    padding: 7px 12px;
    border: 1px solid #facc15;
    background: #fef3c7;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
}

.item {
    background: #f0f2f5;
    padding: 10px;
    border-radius: 6px;
    margin-top: 8px;
}

.manual {
    background: #fff8e1;
    border: 1px solid #ffe08a;
    padding: 10px;
    border-radius: 8px;
    margin-top: 12px;
}

.alerta-amplo {
    background: #fff3cd;
    border: 1px solid #facc15;
    padding: 12px;
    border-radius: 8px;
    margin-top: 12px;
}

.alerta-qtd {
    background: #fde2e2;
    border: 1px solid #f87171;
    padding: 12px;
    border-radius: 8px;
    margin-top: 12px;
}

.toast {
    position: fixed;
    right: 25px;
    bottom: 25px;
    background: #1f2937;
    color: white;
    padding: 12px 16px;
    border-radius: 8px;
    display: none;
}
</style>

<script>
function copiarTexto(texto) {
    navigator.clipboard.writeText(texto);
    var t = document.getElementById("toast");
    t.style.display = "block";
    setTimeout(()=>{t.style.display="none";},1200);
}
</script>

</head>
<body>
<div id="toast" class="toast">Copiado!</div>
""")

        f.write("<h1>Resultado da Pesquisa de Preços - LicitaCon</h1>")

        f.write('<div class="resumo">')
        f.write(f"<p><b>Item pesquisado:</b> {escape(descricao_busca)}</p>")
        f.write(f"<p><b>Descrição sugerida:</b> {escape(descricao_link)}</p>")
        f.write(f"<p><b>Quantidade considerada:</b> {qtd_min} a {qtd_max}</p>")
        f.write(f"<p><b>Total resultados:</b> {min(len(resultados), MAX_RESULTADOS)}</p>")
        f.write("</div>")

        for i, r in enumerate(resultados[:MAX_RESULTADOS], start=1):

            classe = "card"
            if r["modo_busca"] == "amplo":
                classe += " card-amplo"
            if r.get("quantidade_fora"):
                classe += " card-qtd-fora"

            score_class = "score" if r["score"] >= 40 else "score baixo"

            f.write(f'<div class="{classe}">')
            f.write(f'<div class="{score_class}">Resultado {i} - {formatar_percentual(r["score"])}%</div>')
            f.write(f'<div class="modo-tag modo-{r["modo_busca"]}">{r["modo_busca"]}</div>')

            if r["modo_busca"] == "amplo":
                f.write('<div class="alerta-amplo">⚠️ Busca ampla - conferir manualmente</div>')

            if r.get("quantidade_fora"):
                f.write('<div class="alerta-qtd">⚠️ Quantidade fora da faixa</div>')

            if r.get("avisos_tecnicos"):
                f.write('<div class="alerta-qtd">⚠️ <b>Aviso técnico:</b><br>')
                f.write(escape(r["avisos_tecnicos"]))
                f.write('</div>')

            f.write(f"<p><b>Órgão:</b> {escape(str(r['orgao']))}</p>")
            f.write(f"<p><b>Licitação:</b> {r['nr']}/{r['ano']}</p>")
            f.write(f"<p><b>Quantidade:</b> {escape(str(r.get('qtd', '')))}</p>")
            valor_formatado = formatar_moeda_br(r.get("valor_unitario"))
            f.write(f"<p><b>Valor unitário:</b> {escape(valor_formatado)}</p>")

            f.write('<div class="item">')
            f.write(escape(str(r["descricao"])))
            f.write('</div>')

            org = preparar_js(r["orgao"])
            desc = preparar_js(descricao_link)

            f.write('<div class="manual">')
            f.write(f"Órgão: {escape(r['orgao'])} <button class='copy-btn' onclick=\"copiarTexto('{org}')\">📋</button><br>")
            f.write(f"Descrição: {escape(descricao_link)} <button class='copy-btn' onclick=\"copiarTexto('{desc}')\">📋</button><br>")
            f.write(f"Quantidade: {escape(str(r.get('qtd','')))}<br>")
            f.write(f"Valor unitário: {escape(valor_formatado)}<br>")

            copiar_tudo = preparar_js(
                f"Órgão: {r['orgao']} | Descrição: {descricao_link} | Quantidade: {r.get('qtd','')} | Valor: {valor_formatado}"
            )

            f.write(f"<button class='copy-all-btn' onclick=\"copiarTexto('{copiar_tudo}')\">Copiar tudo</button>")
            f.write('</div>')

            link_origem = r.get("link_licitacon") or r.get("link_origem") or LINK_BASE_LICITACON
            f.write(f'<a class="botao" href="{escape(str(link_origem), quote=True)}" target="_blank">Abrir LicitaCon</a>')

            f.write('</div>')

        f.write("</body></html>")

    return nome_arquivo
