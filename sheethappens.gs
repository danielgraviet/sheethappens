// SheetHappens — Google Apps Script
// Install: Extensions → Apps Script → paste this → Save → reload the sheet.
//
// Set your deployed Railway URL here:
var SYNC_URL = "https://YOUR-APP.up.railway.app/sync";

// ---------------------------------------------------------------------------
// Menu setup — runs every time the sheet is opened
// ---------------------------------------------------------------------------
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("SheetHappens")
    .addItem("Sync — This week (7 days)",    "syncWeek")
    .addItem("Sync — Next 2 weeks (14 days)", "syncTwoWeeks")
    .addItem("Sync — Next 30 days",           "syncMonth")
    .addSeparator()
    .addItem("Sync — Custom days...",         "syncCustom")
    .addToUi();
}

// ---------------------------------------------------------------------------
// Preset handlers
// ---------------------------------------------------------------------------
function syncWeek()     { runSync(7);  }
function syncTwoWeeks() { runSync(14); }
function syncMonth()    { runSync(30); }

function syncCustom() {
  var ui = SpreadsheetApp.getUi();
  var response = ui.prompt(
    "SheetHappens — Custom sync",
    "How many days ahead should be fetched? (1–365)",
    ui.ButtonSet.OK_CANCEL
  );
  if (response.getSelectedButton() !== ui.Button.OK) return;

  var days = parseInt(response.getResponseText(), 10);
  if (isNaN(days) || days < 1 || days > 365) {
    ui.alert("Invalid input. Please enter a number between 1 and 365.");
    return;
  }
  runSync(days);
}

// ---------------------------------------------------------------------------
// Core: call the /sync endpoint and show a result toast
// ---------------------------------------------------------------------------
function runSync(days) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet();
  sheet.toast("Syncing assignments for the next " + days + " day(s)...", "SheetHappens", 5);

  try {
    var response = UrlFetchApp.fetch(SYNC_URL + "?days=" + days, {
      method: "get",
      muteHttpExceptions: true,
    });

    var code = response.getResponseCode();
    if (code !== 200) {
      sheet.toast("Sync failed (HTTP " + code + ").", "SheetHappens", 8);
      return;
    }

    var result = JSON.parse(response.getContentText());
    var msg = (
      "Done! Fetched: " + result.total_fetched +
      " | New: "        + result.newly_inserted +
      " | Skipped: "    + result.skipped_duplicates +
      (result.failures > 0 ? " | Failures: " + result.failures : "")
    );
    sheet.toast(msg, "SheetHappens", 10);

  } catch (e) {
    sheet.toast("Error: " + e.message, "SheetHappens", 8);
  }
}
