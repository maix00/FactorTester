import assert from "node:assert/strict";
import test from "node:test";
import {pageObjectKey,pageObjectTitle} from "./page-object.ts";
test("Research tabs deduplicate by identity, never title or directory presentation",()=>{
 const args={researchId:"research:v1:one",researchTitle:"One"};
 assert.equal(pageObjectKey("research-detail",args),pageObjectKey("research-detail",{...args,researchTitle:"Renamed"}));
 assert.notEqual(pageObjectKey("research-detail",args),pageObjectKey("research-detail",{...args,reportId:"report:v1:one"}));
 assert.notEqual(pageObjectKey("research-detail",args),pageObjectKey("research-detail",{...args,localResearch:true,profileId:"self"}));
 assert.notEqual(pageObjectKey("research-detail",{...args,localResearch:true,profileId:"a"}),pageObjectKey("research-detail",{...args,localResearch:true,profileId:"b"}));
 assert.equal(pageObjectTitle("research-detail",{...args,reportTitle:"Report"}),"Report");
 assert.notEqual(pageObjectKey("research-report",{...args,reportId:"report:v1:one"}),pageObjectKey("research-detail",args));
 assert.equal(pageObjectKey("research",{}),undefined);
});
