(function () {
  const tableBody = document.querySelector("#batch-table tbody");
  const addButton = document.querySelector("#add-row");
  const form = document.querySelector("#batch-form");
  const submitButton = document.querySelector("#submit-batch");
  const status = document.querySelector("#sheet-status");
  const progress = document.querySelector("#batch-progress");
  const progressBar = document.querySelector("#batch-progress-bar");
  const progressLabel = document.querySelector("#batch-progress-label");
  const operationalLimit = Number(status?.dataset.operationalLimit || 20);
  const columns = ["item_numero[]", "descricao[]", "quantidade[]"];
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
      status.textContent = `${total} itens detectados. Limite operacional atual: ${operationalLimit} itens.`;
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
  }

  function parseClipboard(text) {
    return text
      .replace(/\r/g, "")
      .split("\n")
      .filter((line) => line.trim().length > 0)
      .map((line) => line.split("\t"));
  }

  function pasteGrid(startInput, text) {
    const parsed = parseClipboard(text);
    if (!parsed.length) {
      return false;
    }

    const startRow = rowIndex(startInput.closest("tr"));
    const startColumn = cellIndex(startInput);
    ensureRows(startRow + parsed.length);

    parsed.forEach((line, rOffset) => {
      line.slice(0, columns.length - startColumn).forEach((value, cOffset) => {
        setCell(startRow + rOffset, startColumn + cOffset, value);
      });
    });

    renumberRows();
    ensureTrailingEmptyRow();

    const targetRowIndex = Math.min(startRow + parsed.length - 1, rows().length - 1);
    const targetColumnIndex = Math.min(startColumn + parsed[0].length, columns.length - 1);
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
      targetColumn = 0;
    }
    if (targetColumn < 0) {
      targetRow = Math.max(0, rowNumber - 1);
      targetColumn = columns.length - 1;
    }

    focusCell(Math.max(0, targetRow), targetColumn);
  }

  function startProgress() {
    const totalDetected = filledRows().length;
    const totalProcessed = totalDetected || 1;
    let percent = 4;
    const startedAt = Date.now();

    if (!progress || !progressBar || !progressLabel) {
      return;
    }

    progress.classList.add("is-active");
    progressBar.style.width = "4%";
    progressLabel.textContent = `Pesquisando item 1 de ${totalProcessed}... 4%`;

    clearInterval(progressTimer);
    progressTimer = setInterval(() => {
      percent = Math.min(92, percent + Math.max(1, Math.round((100 - percent) * 0.08)));
      const current = Math.max(1, Math.min(totalProcessed, Math.ceil((percent / 100) * totalProcessed)));
      const elapsed = Math.round((Date.now() - startedAt) / 1000);
      progressBar.style.width = `${percent}%`;
      progressLabel.textContent = `Pesquisando item ${current} de ${totalProcessed}... ${percent}% · ${elapsed}s`;
    }, 450);
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
        input.value = input.classList.contains("item-number") ? "1" : "";
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
    if (!text.includes("\t") && !text.includes("\n")) {
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
    submitButton.textContent = "Pesquisando...";
    startProgress();
  });

  if (!rows().length) {
    createRow();
  }
  renumberRows();
  ensureTrailingEmptyRow();
})();
