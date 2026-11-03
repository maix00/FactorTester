// Isolated JS model timings. Not browser/HTTP p95. No network or production input.
import { performance } from 'node:perf_hooks';
import { ProductPathRules } from '../../web/app/src/product-selection.ts';
const sample = (count, action) => {
  const values=[];
  for(let i=0;i<count;i++){const start=performance.now();action();values.push(performance.now()-start);}
  values.sort((a,b)=>a-b);return {samples:count,median_ms:values[Math.floor(count/2)],p95_ms:values[Math.floor((count-1)*.95)]};
};
const oldMinimal = values => {
  const ordered=[...new Set(values)].sort((a,b)=>a.length-b.length||a.localeCompare(b));
  return ordered.filter(value=>!ordered.some(parent=>parent!==value&&value.startsWith(parent+'/')));
};
const before=sample(5,()=>oldMinimal(Array.from({length:1000},(_,i)=>'Product/Futures/_products/P'+i)));
const results=[];
for(const n of [1000,10000,100000]){
  const paths=Array.from({length:n},(_,i)=>'Product/Futures/_products/P'+String(i).padStart(6,'0'));
  const build=sample(20,()=>new ProductPathRules(paths));
  const model=new ProductPathRules(paths);
  const lookup=sample(20,()=>{for(let i=0;i<2000;i++)model.state('Product/Futures/_products/P'+String(i).padStart(6,'0'));});
  const toggle=sample(20,()=>model.toggle('Product/Futures/_products/New',true));
  if(model.toggle('Product/Futures',true).join()!=='Product/Futures')throw new Error('path selection expanded or failed compaction');
  results.push({paths:n,build,visible_2000_lookups:lookup,toggle});
}
console.log(JSON.stringify({runtime:process.version,machine:process.arch,fixture:'synthetic in-process model; warm JS; no browser/network',baseline_1000_paths:before,results,heap_used:process.memoryUsage().heapUsed,rss:process.memoryUsage().rss}));
