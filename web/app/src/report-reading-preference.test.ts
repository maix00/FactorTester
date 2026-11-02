import assert from "node:assert/strict";
import test from "node:test";
import { readReportFont, reportFontKey, writeReportFont } from "./report-reading-preference.ts";

test("reading font retains valid per-user preferences and can read the previous key", () => {
  const values = new Map<string,string>([["ft-report-font:alice","20"]]);
  const storage = {getItem:(key:string) => values.get(key) ?? null,setItem:(key:string,value:string) => {values.set(key,value);}};
  assert.equal(readReportFont(storage,"alice"),20);
  writeReportFont(storage,"alice",22);
  assert.equal(values.get(reportFontKey("alice")),"22");
  assert.equal(readReportFont(storage,"alice"),22);
  assert.equal(readReportFont(storage,"bob"),16);
  writeReportFont(storage,"alice",999);
  assert.equal(readReportFont(storage,"alice"),22);
  const unavailable = {getItem:() => {throw new Error("blocked");},setItem:() => {throw new Error("blocked");}};
  assert.equal(readReportFont(unavailable,"alice"),16);
  assert.doesNotThrow(() => writeReportFont(unavailable,"alice",20));
});
