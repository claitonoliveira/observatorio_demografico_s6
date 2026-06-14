# ==========================================================
# OBSERVATÓRIO DEMOGRÁFICO — main.py
# Semana 3: Filtros · Paginação · Autocomplete · Python↔CSS
# Semana 4: SPA · Abas ARIA · Top 5 CSS · Heatmap CSS
#
# PRINCÍPIO ARQUITETURAL:
#   O Python NUNCA injeta inline styles (element.style.color = "x").
#   Toda apresentação vive em style.css. O Python apenas:
#     1. Manipula classes → element.classList.add("status-erro")
#     2. Injeta custom properties → element.style.setProperty("--var", val)
#   Isso separa rigorosamente lógica (Python) de design (CSS).
# ==========================================================

# ----------------------------------------------------------
# IMPORTAÇÕES
# ----------------------------------------------------------
import pandas as pd
from pyscript import document, window   # pyright: ignore[reportMissingImports]
from pyodide.ffi import create_proxy    # pyright: ignore[reportMissingImports]
import io

print("--- Engine de Interatividade Pronto (Semanas 3+4) ---")

# ----------------------------------------------------------
# ESTADOS GLOBAIS DA APLICAÇÃO
# ----------------------------------------------------------
df_global          = None   # DataFrame completo do CSV carregado
df_filtrado_global = None   # Subconjunto após filtros aplicados
pagina_atual       = 1      # Ponteiro de paginação
linhas_por_pagina  = 50     # Tamanho de cada fatia da tabela

# SEMANA 4: controle da aba visível ("tabela" | "analitica")
aba_atual = "tabela"

# ----------------------------------------------------------
# REFERÊNCIAS AOS ELEMENTOS DO DOM (Semana 3)
# ----------------------------------------------------------
status_block       = document.getElementById("status-carregamento")
btn_processar      = document.getElementById("btn-processar")
card_coletada      = document.getElementById("card-coletada")
card_imputada      = document.getElementById("card-imputada")
card_total         = document.getElementById("card-total")
tbody_tabela       = document.getElementById("dados-municipios")
select_uf          = document.getElementById("filtro-uf")
datalist_municipio = document.getElementById("lista-municipios")
btn_anterior       = document.getElementById("btn-anterior")
btn_proximo        = document.getElementById("btn-proximo")
txt_paginacao      = document.getElementById("indicador-pagina")

# SEMANA 4: referências às abas e painéis analíticos
tab_tabela    = document.getElementById("tab-tabela")
tab_analitica = document.getElementById("tab-analitica")
painel_tabela    = document.getElementById("aba-tabela")
painel_analitica = document.getElementById("aba-analitica")
lista_top5    = document.getElementById("top5-lista")
regioes_grid  = document.getElementById("regioes-grid")

# ----------------------------------------------------------
# HELPERS DE FEEDBACK VISUAL (Semana 3 — intactos)
# ----------------------------------------------------------

def _set_status(mensagem: str, tipo: str) -> None:
    """
    Atualiza texto e aparência do bloco de status APENAS via classList.
    tipos: "carregando" | "sucesso" | "erro" | "" (âmbar padrão)
    As classes correspondentes estão definidas em style.css.
    """
    for cls in ("status-carregando", "status-sucesso", "status-erro"):
        status_block.classList.remove(cls)
    if tipo in ("carregando", "sucesso", "erro"):
        status_block.classList.add(f"status-{tipo}")
    status_block.innerText = mensagem


def _set_btn_processando(ativo: bool) -> None:
    """Gerencia .processando e disabled do botão principal."""
    if ativo:
        btn_processar.classList.add("processando")
        btn_processar.setAttribute("disabled", "true")
    else:
        btn_processar.classList.remove("processando")
        btn_processar.removeAttribute("disabled")


def _animar_cards() -> None:
    """
    Reinicia animação .atualizando nos 3 cards de métricas.
    Força reflow (offsetWidth) para que o CSS relance a keyframe.
    """
    for card in (card_coletada, card_imputada, card_total):
        card.parentElement.classList.remove("atualizando")
        _ = card.parentElement.offsetWidth   # força recálculo do layout
        card.parentElement.classList.add("atualizando")


# Inicialização: botão desabilitado até carregar um CSV
_set_status("Inicializando Motor Python e WebAssembly… Por favor, aguarde.", "carregando")
btn_processar.setAttribute("disabled", "true")
btn_processar.classList.add("processando")


# ----------------------------------------------------------
# SEMANA 4 — FUNÇÃO: _trocar_aba
# Gerencia toda a lógica de SPA: ativa a aba clicada,
# desativa a anterior e mostra/oculta os painéis.
# Usa apenas classList e atributos ARIA — zero inline styles.
# ----------------------------------------------------------
def _trocar_aba(aba_id: str) -> None:
    """
    Alterna a visão da SPA entre "tabela" e "analitica".

    Operações realizadas:
      1. Remove .aba-ativa e aria-selected="true" da aba anterior
      2. Adiciona .aba-ativa e aria-selected="true" na nova aba
      3. Gerencia tabindex para navegação via teclado (WCAG 2.1)
      4. Remove `hidden` do painel alvo; adiciona no outro
      5. Se a visão analítica for ativada e houver dados, renderiza gráficos

    O atributo `hidden` nativo do HTML remove o painel do
    fluxo de acessibilidade dos leitores de tela automaticamente.
    """
    global aba_atual

    # Mapeamento: id da aba → (botão, painel)
    abas = {
        "tabela":    (tab_tabela,    painel_tabela),
        "analitica": (tab_analitica, painel_analitica),
    }

    if aba_id not in abas:
        return

    aba_atual = aba_id

    for nome, (botao, painel) in abas.items():
        if nome == aba_id:
            # --- ABA ATIVA ---
            botao.classList.add("aba-ativa")
            botao.setAttribute("aria-selected", "true")
            botao.setAttribute("tabindex", "0")
            painel.removeAttribute("hidden")        # torna visível no DOM
        else:
            # --- ABA INATIVA ---
            botao.classList.remove("aba-ativa")
            botao.setAttribute("aria-selected", "false")
            botao.setAttribute("tabindex", "-1")    # remove do tab-order
            painel.setAttribute("hidden", "")       # oculta no DOM

    print(f"Aba trocada para: '{aba_id}'")

    # Renderiza gráficos ao entrar na visão analítica (se dados disponíveis)
    if aba_id == "analitica" and df_filtrado_global is not None:
        _renderizar_top5()
        _renderizar_heatmap()


# ----------------------------------------------------------
# SEMANA 4 — FUNÇÃO: _renderizar_top5
# Constrói o gráfico de barras horizontais (Top 5 municípios).
# Largura das barras via custom property --bar-width injetada
# com style.setProperty() — nunca style.width diretamente.
# ----------------------------------------------------------
def _renderizar_top5() -> None:
    """
    Renderiza o ranking dos 5 municípios mais populosos como
    gráfico de barras horizontais 100% CSS.

    Estrutura HTML gerada por item:
      <li class="top5-item">
        <div class="top5-header">
          <span class="top5-posicao">#1</span>
          <span class="top5-nome">Município</span>
          <span class="top5-valor">12,345,678</span>
        </div>
        <div class="barra-container">
          <div class="barra" style="--bar-width: 100%"></div>
        </div>
      </li>

    A largura é calculada proporcionalmente ao 1º colocado (100%).
    O CSS em style.css usa `width: var(--bar-width)` para a barra.

    Caso um município específico esteja selecionado através dos filtros,
    o título e a legenda são alterados dinamicamente para refletir a análise individual.
    """
    global df_filtrado_global
    # Captura os elementos de texto do cabeçalho do gráfico
    lbl_titulo_top5 = document.getElementById("titulo-top5")
    lbl_legenda_top5 = document.getElementById("legenda-top5")

    # Proteção: limpa e sai se não há dados
    if df_filtrado_global is None or len(df_filtrado_global) == 0:
        lista_top5.innerHTML = '<li class="top5-vazio">Nenhum dado disponível. Processe os filtros primeiro.</li>'
        return

    # Quantidade de registros que passaram pelos filtros atuais
    qtd_municipios_filtrados = len(df_filtrado_global)

    # ==========================================================
    # CONTROLE DINÂMICO DOS TEXTOS (CONTEXTO DE BUSCA)
    # ==========================================================
    if qtd_municipios_filtrados == 1:
        # Pega o nome do município isolado para colocar diretamente no título
        nome_isolado = str(df_filtrado_global["NOME DO MUNICÍPIO"].iloc[0])
        uf_isolada = str(df_filtrado_global["UF"].iloc[0])
        
        lbl_titulo_top5.innerText = f"Análise Individual · {nome_isolado} ({uf_isolada})"
        lbl_legenda_top5.innerText = "Exibindo a magnitude demográfica do município selecionado"
    else:
        # Se for o estado todo ou o Brasil todo, mantém/restaura o padrão do Top 5
        uf_selecionada = select_uf.value
        if uf_selecionada != "TODOS":
            lbl_titulo_top5.innerText = f"Top 5 Municípios Mais Populosos · {uf_selecionada}"
        else:
            lbl_titulo_top5.innerText = "Top 5 Municípios Mais Populosos"
            
        lbl_legenda_top5.innerText = "Baseado na Pop. Total · Filtros aplicados"

    # Seleciona os 5 maiores por Pop. Total
    top5 = df_filtrado_global.nlargest(5, "POP. TOTAL")

    # Referência para cálculo proporcional (1º lugar = 100%)
    max_pop = top5["POP. TOTAL"].iloc[0]

    if max_pop == 0:
        lista_top5.innerHTML = '<li class="top5-vazio">Dados de população zerados.</li>'
        return

    # Limpa o conteúdo anterior antes de reconstruir
    lista_top5.innerHTML = ""

    for rank, (_, linha) in enumerate(top5.iterrows(), start=1):
        pop_total = int(linha["POP. TOTAL"])
        nome_mun  = str(linha["NOME DO MUNICÍPIO"])
        uf        = str(linha["UF"])

        # Percentual proporcional ao 1º lugar (0–100)
        pct = (pop_total / max_pop) * 100

        # Criação do elemento <li>
        item = document.createElement("li")
        item.className = "top5-item"

        # Linha de cabeçalho: posição + nome + valor
        header_div = document.createElement("div")
        header_div.className = "top5-header"

        span_pos = document.createElement("span")
        span_pos.className = "top5-posicao"
        span_pos.innerText = f"#{rank}"

        span_nome = document.createElement("span")
        span_nome.className = "top5-nome"
        span_nome.innerText = f"{nome_mun} ({uf})"
        span_nome.setAttribute("title", nome_mun)  # tooltip completo

        span_val = document.createElement("span")
        span_val.className = "top5-valor"
        span_val.innerText = f"{pop_total:,}"

        header_div.appendChild(span_pos)
        header_div.appendChild(span_nome)
        header_div.appendChild(span_val)

        # Barra de progresso: container + barra interna
        barra_container = document.createElement("div")
        barra_container.className = "barra-container"

        barra = document.createElement("div")
        barra.className = "barra"

        # SEMANA 4: injeta a custom property --bar-width via setProperty.
        # Isso evita `barra.style.width = "..."` (inline style direto).
        # O CSS em style.css lê: width: var(--bar-width, 0%);
        barra.style.setProperty("--bar-width", f"{pct:.1f}%")

        barra_container.appendChild(barra)
        item.appendChild(header_div)
        item.appendChild(barra_container)
        lista_top5.appendChild(item)

    print(f"Top 5 renderizado: máx={max_pop:,} hab.")


# ----------------------------------------------------------
# SEMANA 4 — FUNÇÃO: _renderizar_heatmap
# Constrói os tiles de macrorregiões 
# ----------------------------------------------------------

# Mapeamento UF → Macrorregião (constante, não muda entre consultas)
_MAPA_REGIOES = {
    "Norte":        ["AC", "AM", "AP", "PA", "RO", "RR", "TO"],
    "Nordeste":     ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"],
    "Centro-Oeste": ["DF", "GO", "MS", "MT"],
    "Sudeste":      ["ES", "MG", "RJ", "SP"],
    "Sul":          ["PR", "RS", "SC"],
}

# Mapeamento auxiliar para identificar a capital de cada UF
_CAPITAIS_UFS = {
    "AC": "Rio Branco", "AL": "Maceió", "AP": "Macapá", "AM": "Manaus",
    "BA": "Salvador", "CE": "Fortaleza", "DF": "Brasília", "ES": "Vitória",
    "GO": "Goiânia", "MA": "São Luís", "MT": "Cuiabá", "MS": "Campo Grande",
    "MG": "Belo Horizonte", "PA": "Belém", "PB": "João Pessoa", "PR": "Curitiba",
    "PE": "Recife", "PI": "Teresina", "RJ": "Rio de Janeiro", "RN": "Natal",
    "RS": "Porto Alegre", "RO": "Porto Velho", "RR": "Boa Vista", "SC": "Florianópolis",
    "SP": "São Paulo", "SE": "Aracaju", "TO": "Palmas"
}

def _renderizar_heatmap() -> None:
    """
    Renderiza contextualmente o bloco inferior direito da aba analítica:
      - Se UF == "TODOS": Exibe as 5 Macrorregiões Brasileiras (Nacional).
      - Se UF específica: Exibe a proporção real entre Capital e Interior daquele Estado,
                          mantendo-se estável mesmo se um município for selecionado.
    """
    global df_filtrado_global, df_global  # Garante o acesso ao DataFrame completo se necessário
    
    uf_selecionada = select_uf.value

    if df_filtrado_global is None or len(df_filtrado_global) == 0:
        regioes_grid.innerHTML = '<div class="regiao-vazia">Nenhum dado disponível.</div>'
        return

    lbl_titulo = document.getElementById("titulo-heatmap")
    lbl_legenda = document.getElementById("legenda-heatmap")
    regioes_grid.innerHTML = ""

    # ==========================================================
    # CASO A: TODOS OS ESTADOS -> EXIBE MACRORREGIÕES (NACIONAL)
    # ==========================================================
    if uf_selecionada == "TODOS":
        lbl_titulo.innerText = "Distribuição por Macrorregião"
        lbl_legenda.innerText = "Intensidade proporcional à participação no total nacional"

        pop_por_uf = df_filtrado_global.groupby("UF")["POP. TOTAL"].sum().to_dict()
        totais_regioes = {}
        for regiao, ufs in _MAPA_REGIOES.items():
            totais_regioes[regiao] = sum(pop_por_uf.get(uf, 0) for uf in ufs)

        total_geral = sum(totais_regioes.values())
        if total_geral == 0: return

        regioes_ordenadas = sorted(totais_regioes.items(), key=lambda x: x[1], reverse=True)

        for regiao, pop in regioes_ordenadas:
            pct = (pop / total_geral) * 100
            opacidade = (pct / 100) * 0.85 + 0.15

            tile = document.createElement("div")
            tile.className = "tile-regiao"

            span_nome = document.createElement("span")
            span_nome.className = "tile-regiao-nome"
            span_nome.innerText = regiao

            span_pct = document.createElement("span")
            span_pct.className = "tile-regiao-pct"
            span_pct.innerText = f"{pct:.1f}%"

            tile.setAttribute("aria-label", f"Região {regiao}: {pct:.1f}% ({int(pop):,} hab.)")
            tile.appendChild(span_nome)
            tile.appendChild(span_pct)
            regioes_grid.appendChild(tile)

    # ==========================================================
    # CASO B: ESTADO ESPECÍFICO -> CAPITAL VS INTERIOR (ESTADUAL ESTÁVEL)
    # ==========================================================
    else:
        lbl_titulo.innerText = f"Distribuição Demográfica · {uf_selecionada}"
        lbl_legenda.innerText = "Concentração populacional real entre a Capital e o Interior do Estado"

        # Criação de um DataFrame exclusivo do Estado, ignorando o filtro de município
        df_estado_completo = df_global[df_global["UF"] == uf_selecionada]

        # Recupera qual é a capital do estado selecionado
        capital_nome = _CAPITAIS_UFS.get(uf_selecionada, "")

        # Filtra a população da capital dentro do escopo total do estado
        df_capital = df_estado_completo[
            df_estado_completo["NOME DO MUNICÍPIO"].str.upper() == capital_nome.upper()
        ]
        pop_capital = df_capital["POP. TOTAL"].sum() if not df_capital.empty else 0

        # O restante da população pertence ao interior (baseado no estado todo)
        total_estado = df_estado_completo["POP. TOTAL"].sum()
        pop_interior = total_estado - pop_capital

        # Dados estruturados para o loop de renderização
        dados_divisao = [
            {"rotulo": f"Capital ({capital_nome})", "pop": pop_capital},
            {"rotulo": "Interior", "pop": pop_interior}
        ]

        # Ordena para manter a consistência térmica do CSS (:first-child pega o maior)
        dados_ordenados = sorted(dados_divisao, key=lambda x: x["pop"], reverse=True)

        for idx, item in enumerate(dados_ordenados):
            pct = (item["pop"] / total_estado) * 100 if total_estado > 0 else 0
            opacidade = (pct / 100) * 0.75 + 0.25

            tile = document.createElement("div")
            tile.className = "tile-regiao"
            
            tile.style.minHeight = "120px" 

            span_nome = document.createElement("span")
            span_nome.className = "tile-regiao-nome"
            span_nome.innerText = item["rotulo"]

            span_pct = document.createElement("span")
            span_pct.className = "tile-regiao-pct"
            span_pct.innerHTML = f"{pct:.1f}% <small style='display:block; font-size:0.75rem; opacity:0.7;'>{int(item['pop']):,} hab.</small>"

            tile.setAttribute("aria-label", f"{item['rotulo']}: {pct:.1f}% com {int(item['pop']):,} habitantes")
            tile.appendChild(span_nome)
            tile.appendChild(span_pct)
            regioes_grid.appendChild(tile)

    print(f"Heatmap analítico fixado no escopo do estado: {uf_selecionada}")


# ----------------------------------------------------------
# MÓDULO AUTOCOMPLETE: DATALIST DINÂMICO (Semana 3 — intacto)
# ----------------------------------------------------------
def atualizar_datalist_municipios(event=None) -> None:
    """Reconstrói o datalist de autocomplete conforme a UF selecionada."""
    global df_global
    if df_global is None:
        return

    uf_selecionada = select_uf.value

    termo_busca = document.getElementById("busca-municipio")
    termo_busca.value = ""

    if uf_selecionada != "TODOS":
        cidades = df_global[df_global["UF"] == uf_selecionada]["NOME DO MUNICÍPIO"].unique()
    else:
        cidades = df_global["NOME DO MUNICÍPIO"].unique()

    cidades_ordenadas = sorted([str(c) for c in cidades])

    options_html = ""
    for cidade in cidades_ordenadas:
        options_html += f'<option value="{cidade}">'

    datalist_municipio.innerHTML = options_html
    print(f"Datalist: {len(cidades_ordenadas)} cidades para UF={uf_selecionada}.")


# ----------------------------------------------------------
# LEITURA DO ARQUIVO LOCAL (Semana 3 — intacto)
# ----------------------------------------------------------
async def ler_arquivo_local(event):
    """Intercepta o upload do CSV e carrega no Pandas via WebAssembly."""
    global df_global

    arquivos = event.target.files
    if len(arquivos) == 0:
        return

    _set_status("Carregando e processando arquivo CSV do Censo…", "carregando")

    try:
        js_file      = arquivos.item(0)
        array_buffer = await js_file.arrayBuffer()
        bytes_data   = array_buffer.to_py().tobytes()

        df_global = pd.read_csv(io.BytesIO(bytes_data))

        _set_status(
            f"Base carregada: {len(df_global):,} municípios. Ajuste os filtros e clique em Processar.",
            "sucesso"
        )
        _set_btn_processando(False)
        atualizar_datalist_municipios()

        tbody_tabela.innerHTML = (
            "<tr><td colspan='6'>📊 Filtros prontos. Clique em 'Processar Dados' para renderizar.</td></tr>"
        )

    except Exception as e:
        _set_status(f"Erro ao ler o arquivo CSV: {e}", "erro")
        _set_btn_processando(True)


# ----------------------------------------------------------
# RENDERIZADOR DA TABELA PAGINADA (Semana 3 — intacto)
# ----------------------------------------------------------
def renderizar_pagina_tabela() -> None:
    """Fatia df_filtrado_global e injeta as linhas na tabela."""
    global df_filtrado_global, pagina_atual, linhas_por_pagina

    if df_filtrado_global is None or len(df_filtrado_global) == 0:
        return

    total_registros = len(df_filtrado_global)
    total_paginas   = ((total_registros - 1) // linhas_por_pagina) + 1

    if pagina_atual < 1:             pagina_atual = 1
    if pagina_atual > total_paginas: pagina_atual = total_paginas

    indice_inicio = (pagina_atual - 1) * linhas_por_pagina
    indice_fim    = indice_inicio + linhas_por_pagina
    df_pagina     = df_filtrado_global.iloc[indice_inicio:indice_fim]

    linhas_html = ""
    for _, linha in df_pagina.iterrows():
        linhas_html += f"""
        <tr>
            <td>{linha['UF']}</td>
            <td>{linha['COD. MUNIC']}</td>
            <td>{linha['NOME DO MUNICÍPIO']}</td>
            <td>{int(linha['POP. COLETADA']):,}</td>
            <td>{int(linha['POP. IMPUTADA']):,}</td>
            <td>{int(linha['POP. TOTAL']):,}</td>
        </tr>
        """
    tbody_tabela.innerHTML = linhas_html

    txt_paginacao.innerText = f"Página {pagina_atual} de {total_paginas}"

    # Habilita/desabilita botões conforme posição do ponteiro
    if pagina_atual == 1:
        btn_anterior.setAttribute("disabled", "true")
    else:
        btn_anterior.removeAttribute("disabled")

    if pagina_atual == total_paginas:
        btn_proximo.setAttribute("disabled", "true")
    else:
        btn_proximo.removeAttribute("disabled")


# ----------------------------------------------------------
# NAVEGAÇÃO DE PÁGINAS (Semana 3 — intacto)
# ----------------------------------------------------------
def ir_pagina_anterior(event):
    global pagina_atual
    if pagina_atual > 1:
        pagina_atual -= 1
        renderizar_pagina_tabela()


def ir_pagina_proxima(event):
    global pagina_atual
    total_paginas = ((len(df_filtrado_global) - 1) // linhas_por_pagina) + 1
    if pagina_atual < total_paginas:
        pagina_atual += 1
        renderizar_pagina_tabela()


# ----------------------------------------------------------
# FILTRAGEM E MOTOR CENTRAL (Semana 3 + extensão Semana 4)
# ----------------------------------------------------------
def processar_filtros(event):
    """
    Função principal: filtra dados, atualiza cards, tabela e gráficos.
    Semana 4: após atualizar a tabela, também (re)renderiza Top 5 e heatmap.
    """
    event.preventDefault()
    global df_global, df_filtrado_global, pagina_atual

    if df_global is None:
        _set_status("⚠️ Nenhuma base carregada. Selecione um arquivo CSV primeiro.", "erro")
        return

    uf_selecionada = select_uf.value
    termo_busca    = document.getElementById("busca-municipio").value.strip().upper()

    _set_btn_processando(True)

    try:
        pagina_atual = 1  # Reset ao processar nova consulta

        # 1. Filtro por UF
        if uf_selecionada != "TODOS":
            df_filtrado_global = df_global[df_global["UF"] == uf_selecionada]
        else:
            df_filtrado_global = df_global.copy()

        # 2. Filtro por nome do município
        if termo_busca:
            municipios_validos = df_filtrado_global["NOME DO MUNICÍPIO"].str.upper().values

            if termo_busca in municipios_validos:
                # Correspondência exata (selecionado via datalist)
                df_filtrado_global = df_filtrado_global[
                    df_filtrado_global["NOME DO MUNICÍPIO"].str.upper() == termo_busca
                ]
            else:
                # Busca parcial (texto livre)
                df_filtrado_global = df_filtrado_global[
                    df_filtrado_global["NOME DO MUNICÍPIO"].str.upper().str.contains(termo_busca, na=False)
                ]

        # 3. Atualização dos cards de métricas
        total_coletado = df_filtrado_global["POP. COLETADA"].sum()
        total_imputado = df_filtrado_global["POP. IMPUTADA"].sum()
        total_geral    = df_filtrado_global["POP. TOTAL"].sum()

        card_coletada.innerText = f"{int(total_coletado):,}"
        card_imputada.innerText = f"{int(total_imputado):,}"
        card_total.innerText    = f"{int(total_geral):,}"
        _animar_cards()

        # 4. Validação de resultado vazio
        if len(df_filtrado_global) == 0:
            tbody_tabela.innerHTML = (
                "<tr><td colspan='6'>Nenhum município encontrado com os filtros aplicados.</td></tr>"
            )
            txt_paginacao.innerText = "Página 0 de 0"
            btn_anterior.setAttribute("disabled", "true")
            btn_proximo.setAttribute("disabled", "true")
            _set_status(
                f"⚠️ Sem resultados para UF={uf_selecionada} | Busca='{termo_busca}'.",
                "erro"
            )
            # Limpa os gráficos também
            lista_top5.innerHTML = '<li class="top5-vazio">Nenhum dado encontrado.</li>'
            regioes_grid.innerHTML = '<div class="regiao-vazia">Nenhum dado encontrado.</div>'
            return

        # 5. Renderiza tabela paginada
        renderizar_pagina_tabela()

        # SEMANA 4: renderiza gráficos analíticos (sempre, não apenas quando a
        # aba estiver ativa — assim ficam prontos quando o usuário alternar).
        _renderizar_top5()
        _renderizar_heatmap()

        total_encontrado = len(df_filtrado_global)
        _set_status(
            f"✅ {total_encontrado:,} município(s) localizado(s). Consulta processada.",
            "sucesso"
        )
        print(f"Filtros processados: {total_encontrado} registros.")

    except Exception as e:
        _set_status(f"❌ Erro ao processar filtros: {e}", "erro")
        print(f"Exceção em processar_filtros: {e}")

    finally:
        _set_btn_processando(False)


# ----------------------------------------------------------
# DETECÇÃO DE TECLA ENTER (Semana 3 — intacto)
# ----------------------------------------------------------
def detectar_enter(event):
    """Captura Enter no campo de busca e executa a filtragem."""
    js_event = event.to_js() if hasattr(event, "to_js") else event
    if getattr(js_event, "key", None) == "Enter":
        event.preventDefault()
        processar_filtros(event)


# ----------------------------------------------------------
# SEMANA 4: HANDLERS DAS ABAS
# Lambdas não funcionam bem com create_proxy no PyScript;
# usamos funções nomeadas para cada aba.
# ----------------------------------------------------------
def _handler_aba_tabela(event):
    """Handler do clique na aba Dados dos Municípios."""
    _trocar_aba("tabela")


def _handler_aba_analitica(event):
    """Handler do clique na aba Visão Analítica."""
    _trocar_aba("analitica")


# Liberação do status inicial após carregamento do Python
_set_status(
    "✅ Ambiente Python pronto! Selecione o arquivo CSV do Censo para iniciar.",
    "sucesso"
)

# ----------------------------------------------------------
# PONTE DE EVENTOS — create_proxy() converte funções Python
# em callbacks JavaScript válidos para addEventListener.
# (Semana 3: todos preservados; Semana 4: novos adicionados)
# ----------------------------------------------------------

# Semana 3
proxy_filtro   = create_proxy(processar_filtros)
proxy_teclado  = create_proxy(detectar_enter)
proxy_upload   = create_proxy(ler_arquivo_local)
proxy_combo_uf = create_proxy(atualizar_datalist_municipios)
proxy_ant      = create_proxy(ir_pagina_anterior)
proxy_prox     = create_proxy(ir_pagina_proxima)

# SEMANA 4: proxies das abas
proxy_aba_tabela    = create_proxy(_handler_aba_tabela)
proxy_aba_analitica = create_proxy(_handler_aba_analitica)

# Vinculação dos eventos — Semana 3
document.getElementById("btn-processar").addEventListener("click",    proxy_filtro)
document.getElementById("busca-municipio").addEventListener("keydown", proxy_teclado)
document.getElementById("upload-csv").addEventListener("change",      proxy_upload)
select_uf.addEventListener("change",                                   proxy_combo_uf)
btn_anterior.addEventListener("click",                                 proxy_ant)
btn_proximo.addEventListener("click",                                  proxy_prox)

# Vinculação dos eventos — SEMANA 4
tab_tabela.addEventListener("click",    proxy_aba_tabela)
tab_analitica.addEventListener("click", proxy_aba_analitica)
