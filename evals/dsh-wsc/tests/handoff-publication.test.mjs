import {test} from 'node:test'
import assert from 'node:assert/strict'
import {buildSelectiveCheckpoint} from '../lib/checkpoint.js'
import {parseSelection} from '../lib/selection.js'
import {prepareContinuity} from '../lib/continuity.js'

const message = text => ({role:'assistant',content:[{type:'text',text}]})

test('line-addressed judgments bind every declared message to retained ranges', () => {
  const messages = [message('The command ran in the recorded checkout.\n' + 'First source context. '.repeat(200)),
    message('The tool printed two passing checks.\n' + 'Second source context. '.repeat(200))]
  const result = buildSelectiveCheckpoint({messages}, {
    selectionAddress: 'lines',
    ranges: [{source: 'm1', from: 1, to: 1}, {source: 'm2', from: 1, to: 1}],
    facts: [{text: 'Two checks passed in the recorded checkout.', sources: ['m1', 'm2']},
      {text: 'The third message proved coverage.', sources: ['m1', 'm3']}],
  })
  assert.deepEqual(result.keptFacts, [{text: 'Two checks passed in the recorded checkout.', sources: ['s1', 's2']}])
  assert.equal(result.droppedFacts, 1)
})

test('continuity restores only controls from the selected checkpoint ancestry', () => {
  const user = text => ({role:'user',source:{kind:'user'},content:[{type:'text',text}]})
  const prior = {role:'user',source:{kind:'checkpoint',compactionId:'selected'},
    content:[{type:'text',text:'truncated control'}]}
  const events = [
    {seq:1,type:'user/message',data:user('Unrelated historical request.')},
    {seq:2,type:'compaction/summary',data:{compactionId:'other',shadowedSeqs:[1]}},
    {seq:3,type:'user/message',data:user('The output must match across runs on the same input.')},
    {seq:4,type:'compaction/summary',data:{compactionId:'selected',shadowedSeqs:[3]}},
    {seq:5,type:'user/message',data:prior},
  ]
  const session = {events,deriveEventMessage:event => event.data}
  const input = {messages:[prior]}
  const isCheckpointSource = source => source?.kind === 'checkpoint'
  const view = prepareContinuity(input,session,isCheckpointSource)
  assert.match(view.control,/on the same input/)
  assert.doesNotMatch(view.control,/Unrelated historical request/)
  assert.throws(() => prepareContinuity(input,{...session,events:events.slice(4)},
    isCheckpointSource),/continuity_control_source_unavailable/)
})

test('a parsed state accompanies complete evidence without certifying it', () => {
  const quote='The source file was changed; the check has not run yet.'
  const selection=parseSelection(JSON.stringify({keep:[quote],state:'The implementation was changed. Its check remains open.'}))
  const result=buildSelectiveCheckpoint({messages:[message(quote+' context'.repeat(300))]},
    {...selection,state:selection.state})
  assert.ok(result.text.includes(quote))
  assert.ok(result.text.includes(selection.state))
  assert.ok(result.text.includes('model account'))
  assert.ok(result.text.includes('model account; unverified'))
})

test('runtime receipts expose workdir for equal paths and commands', () => {
  const events = ['D:/project-a', 'D:/project-b'].map((workdir, index) => ({
    seq: index + 1, type: 'assistant/message', data: {role: 'assistant', content: [
      {type: 'tool-call', id: `write-${index}`, name: 'write', arguments: {path: 'main.py', workdir}},
      {type: 'tool-call', id: `shell-${index}`, name: 'pwsh', arguments: {command: 'node --test', workdir}},
    ]},
  }))
  const view = prepareContinuity({messages: []}, {events, deriveEventMessage: e => e.data}, () => false)
  assert.match(view.runtime, /main\.py.*workdir: "D:\/project-a"/)
  assert.match(view.runtime, /main\.py.*workdir: "D:\/project-b"/)
  assert.match(view.runtime, /node --test.*workdir: "D:\/project-a"/)
  assert.match(view.runtime, /node --test.*workdir: "D:\/project-b"/)
  assert.match(view.runtime, /unknown/)
})

test('tight budgets publish a whole source or reject, never certify missing excerpts', () => {
  const quote='A'.repeat(200)
  const input={messages:[{role:'user',source:{kind:'user'},content:[{type:'text',text:'Binding instruction. '.repeat(50)}]},message(quote+' padding'.repeat(500))]}
  for(const maxChars of [600,900,1200,1800]) {
    const result=buildSelectiveCheckpoint(input,{quotes:[quote],controlItemCap:0,payload:{maxChars}})
    if(result!==null) {
      assert.ok(result.text.includes(quote))
      assert.equal(result.selectedCount,1)
      assert.ok(Buffer.byteLength(result.text)<=result.budget)
    }
  }
})

test('judgments never cite a source that budget packing omitted', () => {
  const short='First source: the action is pending; the literal [s2] is quoted text, not a source label.'
  const long='Second source: '+ 'x'.repeat(1000)
  const input={messages:[message(short+' '+long+' padding'.repeat(500))]}
  const result=buildSelectiveCheckpoint(input,{quotes:[short,long],payload:{maxChars:900},facts:[
    {text:'Still pending.',sources:[short]}, {text:'This must not survive alone.',sources:[long]}]})
  assert.ok(result)
  assert.ok(!result.text.includes('This must not survive alone.'))
  assert.ok(result.keptFacts.every(f=>f.sources.every(ref=>result.text.includes(`[${ref}]`))))
})

test('an oversized narrative is discarded as a unit, not cut mid-claim', () => {
  const selection=parseSelection(JSON.stringify({keep:['Supported source observation.'],state:'x'.repeat(1300)}))
  assert.equal(selection.state,'')
})

test('a judgment is not published on only a surviving subset of its declared sources', () => {
  const old='The old JSON had three keys.'
  const missing='The edited JSON now includes the version key.'
  const fact='The JSON was changed from three keys to four including version.'
  const input={messages:[message(old+' padding'.repeat(1500))]}
  const options={quotes:[old],facts:[{text:fact,sources:[old,missing]}]}
  const legacy=buildSelectiveCheckpoint(input,options)
  const strict=buildSelectiveCheckpoint(input,{...options,requireAllFactSources:true})
  assert.ok(legacy.text.includes(fact))
  assert.ok(strict)
  assert.ok(!strict.text.includes(fact))
  assert.equal(strict.judgmentCount,0)
  assert.equal(strict.droppedFacts,1)
  assert.equal(strict.selectedCount,legacy.selectedCount)
})

test('complete dependencies survive nested-quote deduplication with real retained refs', () => {
  const short='The old JSON had three keys.'
  const enclosing=short+' The original source is quoted in full.'
  const current='The observed new JSON has four keys and includes version.'
  const fact='The old and observed new JSON differ in key count.'
  const input={messages:[message(enclosing+' '+current+' padding'.repeat(1800))]}
  const strict=buildSelectiveCheckpoint(input,{quotes:[short,enclosing,current],
    facts:[{text:fact,sources:[short,current]}],requireAllFactSources:true})
  assert.ok(strict.text.includes(fact))
  assert.equal(strict.judgmentCount,1)
  assert.equal(strict.keptFacts[0].sources.length,2)
})
