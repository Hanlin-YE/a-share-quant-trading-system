import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = process.argv[2];
if (!workbookPath) {
  throw new Error("Usage: node inspect_portfolio_workbook.mjs <workbook.xlsx>");
}

const input = await FileBlob.load(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(input);

const sheets = workbook.worksheets.map((sheet) => sheet.name);
console.log(JSON.stringify({ sheets }, null, 2));

for (const sheetName of sheets) {
  const inspection = await workbook.inspect({
    kind: "table",
    range: `${sheetName}!A1:Z30`,
    include: "values,formulas",
    tableMaxRows: 30,
    tableMaxCols: 26,
  });
  console.log(`--- ${sheetName} ---`);
  console.log(inspection.ndjson);
}
