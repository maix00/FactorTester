import test from "node:test";
import assert from "node:assert/strict";
import {sourceIdentity, sourceTitle, sourceCapability, bookTypes} from "./source-model.ts";
test("source identity and capability keep provider snapshot and current-service scope separate", () => {
 assert.equal(sourceIdentity({family_id:"family",id:"member"}),"family");
 assert.equal(sourceTitle({family_name:"Rates"}),"Rates");
 const snapshot={adapter_available:false,supported_book_types:[]};
 const service={market_data_sources:{members:[{member_key:"M",adapter_available:true},{member_key:"other",supported_book_types:["L3_MBO"]}]}};
 assert.equal(sourceCapability({id:"M",nautilus_capability:snapshot},service).value,snapshot);
 assert.equal(sourceCapability({id:"M"},service).origin,"service");
 assert.equal(sourceCapability({id:"absent"},service).origin,"missing");
 assert.deepEqual(bookTypes({simulated_venue_config:{fields:[{path:"book_type",options:[{value:"L1_MBP"},"L2_MBP"]}]}}),["L1_MBP","L2_MBP"]);
});
