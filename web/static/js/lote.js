(function () {
  const tableBody = document.querySelector("#batch-table tbody");
  const addButton = document.querySelector("#add-row");
  const form = document.querySelector("#batch-form");
  const submitButton = document.querySelector("#submit-batch");
  const status = document.querySelector("#sheet-status");
  const progress = document.querySelector("#batch-progress");
  const progressBar = document.querySelector("#batch-progress-bar");
  const progressLabel = document.querySelector("#batch-progress-label");
  const sourceAll = document.querySelector("[data-source-all]");
  const sourceItems = [...document.querySelectorAll("[data-source-item]")];
  const activeWorkspaceRow = document.querySelector(".workspace-row.is-active");
  const periodRadios = [...document.querySelectorAll('input[name="periodo_pesquisa"]')];
  const customPeriodFields = [...document.querySelectorAll("[data-period-custom]")];
  const quantityInput = document.querySelector('input[name="quantidade_item"]');
  const toleranceInput = document.querySelector('.operational-filters input[name="tolerancia_percentual"]');
  const quantityRangeOutput = document.querySelector("[data-quantity-range-output]");
  const workspaceGrid = document.querySelector("[data-workspace-grid]");
  const workspaceNavToggle = document.querySelector("[data-workspace-nav-toggle]");
  const operationalLimit = Number(status?.dataset.operationalLimit || 20);
  const columns = ["item_numero[]", "descricao[]", "quantidade[]", "unidade[]"];
  const dataColumnStart = 1;
  const dataColumnNames = ["descricao[]", "quantidade[]", "unidade[]"];
  let progressTimer = null;

  function rows() {
    return [...tableBody.querySelectorAll("tr")];
  }

  function cells(row) {
    return columns.map((name) => row.querySelector(`input[name="${name}"]`));
  }

  function rowIndex(row) {
    return rows().indexOf(row);
  }

  function cellIndex(input) {
    return cells(input.closest("tr")).indexOf(input);
  }

  function columnByName(row, name) {
    return row.querySelector(`input[name="${name}"]`);
  }

  function filledRows() {
    return rows().filter((row) => {
      const [, description, quantity] = cells(row);
      return description.value.trim() || quantity.value.trim();
    });
  }

  function updateStatus() {
    const total = filledRows().length;
    if (!status) {
      return;
    }
    if (total > operationalLimit) {
      status.textContent = `${total} itens detectados. A importacao usara os primeiros ${operationalLimit} itens nesta versao.`;
      status.classList.add("is-warning");
    } else if (total > 0) {
      status.textContent = `${total} item(ns) detectado(s).`;
      status.classList.remove("is-warning");
    } else {
      status.textContent = "Cole dados do Excel ou preencha a primeira linha.";
      status.classList.remove("is-warning");
    }
  }

  function renumberRows() {
    rows().forEach((row, index) => {
      row.dataset.rowIndex = String(index);
      const numberInput = row.querySelector(".item-number");
      if (numberInput) {
        numberInput.value = String(index + 1);
      }
      cells(row).forEach((input, columnIndex) => {
        input.id = `lote-${index + 1}-${columnIndex + 1}`;
      });
    });
    updateStatus();
  }

  function createRow(focusColumn) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td><input class="item-number sheet-cell" type="text" name="item_numero[]" value=""></td>
      <td><input class="sheet-cell description-cell" type="text" name="descricao[]" value="" placeholder="Descrição do item"></td>
      <td><input class="sheet-cell quantity-cell" type="text" name="quantidade[]" value="" inputmode="decimal" placeholder="0"></td>
      <td><input class="sheet-cell unit-cell" type="text" name="unidade[]" value="UN" maxlength="12" placeholder="UN"></td>
      <td><button class="icon-button remove-row" type="button" title="Remover linha">×</button></td>
    `;
    tableBody.appendChild(row);
    renumberRows();

    if (typeof focusColumn === "number") {
      cells(row)[focusColumn].focus();
    }
    return row;
  }

  function ensureRows(count) {
    while (rows().length < count) {
      createRow();
    }
  }

  function isRowEmpty(row) {
    const [, description, quantity] = cells(row);
    return !description.value.trim() && !quantity.value.trim();
  }

  function ensureTrailingEmptyRow() {
    const currentRows = rows();
    const last = currentRows[currentRows.length - 1];
    if (last && !isRowEmpty(last)) {
      createRow();
    }
    updateStatus();
  }

  function setCell(rowNumber, columnNumber, value) {
    ensureRows(rowNumber + 1);
    const row = rows()[rowNumber];
    const input = row ? cells(row)[columnNumber] : null;
    if (!input) {
      return;
    }

    input.value = String(value || "").trim();
    if (input.name === "unidade[]" && !input.value) {
      input.value = "UN";
    }
  }

  function setCellByName(rowNumber, name, value) {
    ensureRows(rowNumber + 1);
    const row = rows()[rowNumber];
    const input = row ? columnByName(row, name) : null;
    if (!input) {
      return;
    }
    input.value = String(value || "").trim();
    if (name === "quantidade[]" && !input.value) {
      input.value = "0";
    }
    if (name === "unidade[]" && !input.value) {
      input.value = "UN";
    }
  }

  function parseClipboard(text) {
    const rowsParsed = [];
    let row = [];
    let value = "";
    let inQuotes = false;
    const normalized = String(text || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");

    for (let index = 0; index < normalized.length; index += 1) {
      const char = normalized[index];
      const next = normalized[index + 1];

      if (char === '"') {
        if (inQuotes && next === '"') {
          value += '"';
          index += 1;
        } else {
          inQuotes = !inQuotes;
        }
        continue;
      }

      if (char === "\t" && !inQuotes) {
        row.push(value);
        value = "";
        continue;
      }

      if (char === "\n" && !inQuotes) {
        row.push(value);
        if (row.some((cell) => String(cell || "").trim().length > 0)) {
          rowsParsed.push(row);
        }
        row = [];
        value = "";
        continue;
      }

      value += char;
    }

    row.push(value);
    if (row.some((cell) => String(cell || "").trim().length > 0)) {
      rowsParsed.push(row);
    }
    return rowsParsed;
  }

  function pasteGrid(startInput, text) {
    const parsed = parseClipboard(text);
    if (!parsed.length) {
      return false;
    }

    const startRow = rowIndex(startInput.closest("tr"));
    const pastedColumns = Math.max(...parsed.map((line) => line.length));
    const rawStartColumn = cellIndex(startInput);
    const pasteAsItemData = pastedColumns <= dataColumnNames.length && rawStartColumn <= dataColumnStart;
    const startColumn = pasteAsItemData ? dataColumnStart : rawStartColumn;
    ensureRows(startRow + parsed.length);

    parsed.forEach((line, rOffset) => {
      if (pasteAsItemData) {
        dataColumnNames.forEach((name, index) => {
          const fallback = name === "quantidade[]" ? "0" : name === "unidade[]" ? "UN" : "";
          setCellByName(startRow + rOffset, name, line[index] ?? fallback);
        });
        return;
      }

      line.slice(0, columns.length - startColumn).forEach((value, cOffset) => {
        setCell(startRow + rOffset, startColumn + cOffset, value);
      });
    });

    renumberRows();
    ensureTrailingEmptyRow();

    const targetRowIndex = Math.min(startRow + parsed.length - 1, rows().length - 1);
    const targetColumnIndex = pasteAsItemData
      ? Math.min(dataColumnStart + Math.min(pastedColumns, dataColumnNames.length) - 1, columns.length - 1)
      : Math.min(startColumn + parsed[0].length, columns.length - 1);
    const targetCell = cells(rows()[targetRowIndex])[targetColumnIndex];
    if (targetCell) {
      targetCell.focus();
      targetCell.select();
    }
    return true;
  }

  function focusCell(rowNumber, columnNumber) {
    ensureRows(rowNumber + 1);
    const row = rows()[rowNumber];
    const input = row ? cells(row)[columnNumber] : null;
    if (input) {
      input.focus();
      input.select();
    }
  }

  function moveFocus(input, rowDelta, columnDelta) {
    const rowNumber = rowIndex(input.closest("tr"));
    const columnNumber = cellIndex(input);
    let targetRow = rowNumber + rowDelta;
    let targetColumn = columnNumber + columnDelta;

    if (targetColumn >= columns.length) {
      targetRow = rowNumber + 1;
      targetColumn = dataColumnStart;
    }
    if (targetColumn < 0) {
      targetRow = Math.max(0, rowNumber - 1);
      targetColumn = columns.length - 1;
    }

    focusCell(Math.max(0, targetRow), targetColumn);
  }

  function startProgress() {
    const totalDetected = filledRows().length;
    const totalProcessed = Math.min(totalDetected || 1, operationalLimit);
    let percent = 4;
    const startedAt = Date.now();

    if (!progress || !progressBar || !progressLabel) {
      return;
    }

    progress.classList.add("is-active");
    progressBar.style.width = "4%";
    progressLabel.textContent = `Importando ${totalProcessed} item(ns)... 4%`;

    clearInterval(progressTimer);
    progressTimer = setInterval(() => {
      percent = Math.min(92, percent + Math.max(1, Math.round((100 - percent) * 0.08)));
      const current = Math.max(1, Math.min(totalProcessed, Math.ceil((percent / 100) * totalProcessed)));
      const elapsed = Math.round((Date.now() - startedAt) / 1000);
      const avgPerItem = elapsed / Math.max(1, current);
      const remaining = Math.max(0, Math.round(avgPerItem * (totalProcessed - current)));
      progressBar.style.width = `${percent}%`;
      progressLabel.textContent = `Importando item ${current} de ${totalProcessed}... Tempo: ${elapsed}s · Estimativa restante: ${remaining}s`;
    }, 450);
  }

  function syncSourceAll() {
    if (!sourceAll || !sourceItems.length) {
      return;
    }
    sourceAll.checked = sourceItems.every((item) => item.checked);
  }

  if (sourceAll && sourceItems.length) {
    sourceAll.addEventListener("change", () => {
      sourceItems.forEach((item) => {
        if (!item.disabled) {
          item.checked = sourceAll.checked;
        }
      });
    });

    sourceItems.forEach((item) => {
      item.addEventListener("change", syncSourceAll);
    });
    syncSourceAll();
  }

  function syncPeriodFields() {
    if (!periodRadios.length || !customPeriodFields.length) {
      return;
    }
    const selected = periodRadios.find((radio) => radio.checked)?.value;
    const showCustom = selected === "personalizado";
    customPeriodFields.forEach((field) => {
      field.classList.toggle("is-hidden", !showCustom);
    });
  }

  periodRadios.forEach((radio) => {
    radio.addEventListener("change", syncPeriodFields);
  });
  syncPeriodFields();

  function parseDecimal(value) {
    const normalized = String(value || "")
      .replace(/[^\d,.-]/g, "")
      .replace(",", ".");
    const parsed = Number.parseFloat(normalized);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function formatRangeNumber(value) {
    if (!Number.isFinite(value)) {
      return "0";
    }
    return value
      .toFixed(2)
      .replace(/\.?0+$/, "");
  }

  function syncQuantityRange() {
    if (!quantityInput || !toleranceInput || !quantityRangeOutput) {
      return;
    }
    const quantity = parseDecimal(quantityInput.value);
    const tolerance = parseDecimal(toleranceInput.value);
    if (quantity === null || tolerance === null) {
      quantityRangeOutput.textContent = "-";
      return;
    }
    const factor = Math.max(0, tolerance) / 100;
    const min = Math.max(0, quantity - quantity * factor);
    const max = quantity + quantity * factor;
    quantityRangeOutput.textContent = `${formatRangeNumber(min)} a ${formatRangeNumber(max)}`;
  }

  [quantityInput, toleranceInput].forEach((input) => {
    if (input) {
      input.addEventListener("input", syncQuantityRange);
      input.addEventListener("change", syncQuantityRange);
    }
  });
  syncQuantityRange();

  function applyWorkspaceNavState(collapsed) {
    if (!workspaceGrid) {
      return;
    }
    workspaceGrid.classList.toggle("nav-collapsed", collapsed);
    if (workspaceNavToggle) {
      workspaceNavToggle.textContent = collapsed ? "Mostrar itens" : "Ocultar itens";
      workspaceNavToggle.setAttribute("aria-expanded", String(!collapsed));
    }
  }

  if (workspaceGrid) {
    const storedState = localStorage.getItem("workspaceBasketCollapsed");
    applyWorkspaceNavState(storedState === null ? true : storedState === "true");
  }

  if (workspaceNavToggle) {
    workspaceNavToggle.addEventListener("click", () => {
      const next = !workspaceGrid.classList.contains("nav-collapsed");
      localStorage.setItem("workspaceBasketCollapsed", String(next));
      applyWorkspaceNavState(next);
    });
  }

  addButton.addEventListener("click", () => {
    createRow(1);
  });

  tableBody.addEventListener("click", (event) => {
    const removeButton = event.target.closest(".remove-row");
    if (!removeButton) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();

    const currentRows = rows();
    if (currentRows.length <= 1) {
      cells(currentRows[0]).forEach((input) => {
        if (input.classList.contains("item-number")) {
          input.value = "1";
        } else if (input.name === "unidade[]") {
          input.value = "UN";
        } else {
          input.value = "";
        }
      });
      updateStatus();
      return;
    }

    removeButton.closest("tr").remove();
    renumberRows();
    updateStatus();
  });

  tableBody.addEventListener("input", (event) => {
    if (!event.target.matches("input")) {
      return;
    }
    ensureTrailingEmptyRow();
  });

  tableBody.addEventListener("paste", (event) => {
    const input = event.target;
    if (!input.matches("input")) {
      return;
    }

    const text = event.clipboardData.getData("text/plain");
    const pastedIntoAutoNumber = input.name === "item_numero[]";
    if (!pastedIntoAutoNumber && !text.includes("\t") && !text.includes("\n")) {
      return;
    }

    event.preventDefault();
    pasteGrid(input, text);
  });

  tableBody.addEventListener("keydown", (event) => {
    const input = event.target;
    if (!input.matches("input")) {
      return;
    }

    if (event.key === "Enter") {
      event.preventDefault();
      moveFocus(input, 1, 0);
      ensureTrailingEmptyRow();
    }

    if (event.key === "Tab") {
      event.preventDefault();
      moveFocus(input, 0, event.shiftKey ? -1 : 1);
    }
  });

  form.addEventListener("submit", () => {
    submitButton.disabled = true;
    submitButton.textContent = "Importando...";
    startProgress();
  });

  if (!rows().length) {
    createRow();
  }
  renumberRows();
  ensureTrailingEmptyRow();
  if (activeWorkspaceRow) {
    activeWorkspaceRow.scrollIntoView({ block: "nearest" });
  }
})();
