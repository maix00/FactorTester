import assert from "node:assert/strict";
import test from "node:test";
import {readConfigurationView} from "./navigation.ts";
test("legacy configuration links still decode field paths and reject unknown views", () => {
 assert.deepEqual(readConfigurationView('?tr_config=field&tr_path=%5B%22analyses%22%2C%22backtest%22%5D'),{page:"field",id:undefined,path:["analyses","backtest"]});
 assert.deepEqual(readConfigurationView('?tr_config=unknown'),{page:"overview"});
});
