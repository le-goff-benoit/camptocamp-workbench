import test from 'node:test';
import assert from 'node:assert/strict';
import { taskMeasures } from '../web/measurements.mjs';
test('unknown effort and empty estimates stay unknown, not zero',()=>{
  const result=taskMeasures([],[]);
  assert.equal(result.actual,null);assert.equal(result.initial,null);assert.equal(result.tokens,null);
});
test('recorded effort wins over native observations without double counting',()=>{
  const result=taskMeasures([{actual_minutes:10,time_complete:true,initial:{expected_minutes:20},tokens:{total_tokens:120},token_complete:true}], [{usage:{active_seconds:600,tokens:{total_tokens:120},complete:true,tokens_complete:true}}]);
  assert.equal(result.actual,10);assert.equal(result.tokens,120);assert.equal(result.delta,-10);
});
test('incomplete measurements expose only a partial subtotal',()=>{
  const result=taskMeasures([{actual_minutes:null,known_minutes:5,time_complete:false,initial:{expected_minutes:20},known_tokens:50,token_complete:false}],[]);
  assert.equal(result.actual,5);assert.equal(result.partial,true);assert.equal(result.delta,null);
});
