"""Editor contracts through rendered Ant Design controls; HTTP authority is a fixture."""
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import json,re,subprocess,threading
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[2]
APP=ROOT/'web/app'

def test_factor_family_set_and_parameter_editors(tmp_path):
    imports={key:json.dumps(str(APP/path)) for key,path in {
        'REACT':'node_modules/react/index.js','DOM':'node_modules/react-dom/client.js',
        'FAMILY':'src/components/factor-family-editor.tsx','SETEDITOR':'src/components/factor-set-editor.tsx',
        'CATEGORY':'src/components/category-editor.tsx','LIBRARY':'src/components/library-create.tsx','I18N':'src/i18n.ts','CSS':'src/shell.css',
    }.items()}
    source='''
import React from REACT;import {createRoot} from DOM;
import {FactorFamilyEditor} from FAMILY;import {FactorSetEditor} from SETEDITOR;import {LibraryCreate} from LIBRARY;import {CategoryEditor} from CATEGORY;
import I18N;import CSS;
window.calls=[];window.saved=[];
const frozen={ref:'factor:v2:a',alias:'Factor A',params:{N:20},identity:{family_alias:'Alpha'}};
window.fetch=async(url,options={})=>{
 const u=new URL(url,location.origin),body=options.body?JSON.parse(options.body):null;
 window.calls.push({path:u.pathname,query:u.search,method:options.method||'GET',body});
 const ok=value=>new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});
 if(u.pathname==='/api/factor-library/families')return ok({families:[{factor_family_alias:'Alpha',factor_family_name:'Alpha',source:'custom',owner_username:'alice'}]});
 if(u.pathname==='/api/factor-library/families/validate')return ok({valid:true,params:[{alias:'N',name:'N',type:'WindowParam',default_value:'2d'}]});
 if(u.pathname==='/api/factor-library/factors')return ok({factors:[{ref:frozen.ref,alias:frozen.alias,owner_username:'alice'}]});
 if(u.pathname==='/api/factor-library/factors/detail'){const data={factor:{...frozen,ref:u.searchParams.get('factor_ref')||frozen.ref}};if(window.deferDetail){window.deferDetail=false;return new Promise(resolve=>window.releaseDetail=()=>resolve(ok(data)));}return ok(data);}
 if(u.pathname==='/api/factor-library/factor-sets/descriptor'){
  if(window.failDescriptor)return new Response(JSON.stringify({error:'unavailable'}),{status:503});
  return ok({descriptor:{manifest:{alias:'Existing set',identity:{set_id:'set-1',members:[frozen]}}}});
 }
 if(u.pathname==='/api/factor-library/families/custom/Alpha'&&!options.method)return ok({factor:{name:'Alpha',chinese_name:'Existing family',source_code:'old source',can_edit:true}});
 if(options.method==='POST'||options.method==='PUT')return ok({factor:{...frozen,id:'Alpha'},factor_set:{target_ref:'factor-set:v1:new',...body.definition}});
 throw Error('unexpected editor request');
};
function Harness(){const [mode,setMode]=React.useState('family-new');return <main>
 <nav>{['family-new','family-edit','set-new','set-edit','set-failed','factor-edit','category-edit','composite-edit','factor-nested'].map(value=><button key={value} onClick={()=>{window.failDescriptor=value==='set-failed';setMode(value);}}>{value}</button>)}</nav>
 {mode.startsWith('family')?<FactorFamilyEditor key={mode} family={mode==='family-edit'?{factor_family_alias:'Alpha',owner_username:'alice'}:undefined} onSaved={v=>window.saved.push(v)} onCancel={()=>{}}/>:
 mode.endsWith('edit')&&mode.includes('category')||mode==='composite-edit'?<CategoryEditor key={mode} category={{id:'category:1',alias:'Segments',is_composite:mode==='composite-edit',items:[{label:'First',paths:['Product/A/']},{label:'Others',paths:['Product/B/'],label_generated:true}]}} onSaved={v=>window.saved.push(v)} onDeleted={()=>{}} onCancel={()=>{}}/>:
 mode.startsWith('factor-')?<LibraryCreate key={mode} kind='factor' factor={{...frozen,factor_family_alias:'Alpha',parameter_definitions:mode==='factor-nested'?[{alias:'Child',name:'Nested',type:'FactorParam',input_mode:'factor_ref_custom',options:[{value:'CA',label:'Close'}]}]:[{alias:'N',name:'Window',type:'WindowParam',input_mode:'text'}]}} onCreated={v=>window.saved.push(v)} onCancel={()=>{}}/>:
 <FactorSetEditor key={mode} value={mode==='set-new'?undefined:{target_ref:'factor-set:v1:old',set_id:'set-1',owner_username:'alice'}} onSaved={v=>window.saved.push(v)} onCancel={()=>{}}/>}
 </main>}
createRoot(document.getElementById('root')).render(<Harness/>);
'''
    for key,value in imports.items():source=source.replace(key,value)
    harness=tmp_path/'harness.tsx';harness.write_text(source)
    subprocess.run([str(APP/'node_modules/.bin/esbuild'),str(harness),'--bundle','--format=iife',f'--outfile={tmp_path/"harness.js"}'],cwd=APP,check=True,capture_output=True)
    (tmp_path/'index.html').write_text('<link rel="stylesheet" href="harness.css"><div id="root"></div><script src="harness.js"></script>')
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(tmp_path)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            try:
                for width in (1200,390):
                    page=browser.new_page(viewport={'width':width,'height':850});page.set_default_timeout(8000)
                    errors=[];page.on('pageerror',lambda e:errors.append(type(e).__name__))
                    page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                    name=page.get_by_label('Name',exact=True);source=page.get_by_label('Source',exact=True)
                    name.fill('Display only')
                    page.locator('input[type=file]').set_input_files({'name':'Alpha.py','mimeType':'text/x-python','buffer':b'class Alpha(FactorFamily): pass'})
                    expect(source).to_have_value('class Alpha(FactorFamily): pass')
                    page.get_by_role('button',name='Validate',exact=True).click()
                    page.get_by_role('cell',name='WindowParam',exact=True).wait_for()
                    page.get_by_role('button',name='Save',exact=True).click();page.wait_for_function('window.saved.length===1')
                    call=page.evaluate('window.calls.find(c=>c.method==="POST"&&c.path.endsWith("/families/custom"))')
                    assert call['path']=='/api/factor-library/families/custom'
                    assert call['body']['chinese_name']=='Display only' and call['body']['source_code'].startswith('class Alpha')
                    page.get_by_role('button',name='family-edit',exact=True).click();source=page.get_by_label('Source',exact=True)
                    source.wait_for();expect(source).to_have_value("old source")
                    source.fill('class Alpha(FactorFamily): updated=True');page.get_by_role('button',name='Save',exact=True).click()
                    page.wait_for_function('window.saved.length===2')
                    assert page.evaluate('window.calls.some(c=>c.method==="PUT"&&c.path.endsWith("/Alpha"))')
                    page.get_by_role('button',name='set-new',exact=True).click();page.get_by_label('Name',exact=True).fill('Selected factors')
                    page.get_by_role('combobox').click();page.locator('.ant-select-item-option').filter(has_text='Factor A').click();page.keyboard.press('Escape')
                    page.get_by_role('button',name='Save',exact=True).click();page.wait_for_function('window.saved.length===3')
                    body=page.evaluate('window.calls.filter(c=>c.path==="/api/factor-library/factor-sets"&&c.method==="POST").at(-1).body')
                    assert body['definition']['members'][0]['ref']=='factor:v2:a'
                    page.get_by_role('button',name='set-edit',exact=True).click();page.get_by_role('button',name='Save',exact=True).click()
                    page.wait_for_function('window.saved.length===4')
                    body=page.evaluate('window.calls.filter(c=>c.path==="/api/factor-library/factor-sets"&&c.method==="POST").at(-1).body')
                    assert body['replace_target_ref']=='factor-set:v1:old' and body['definition']['set_id']=='set-1'
                    assert body['definition']['members'][0]['params']=={'N':20}
                    page.get_by_role('button',name='set-failed',exact=True).click()
                    page.wait_for_function('window.calls.filter(c=>c.path.endsWith("/descriptor")).length===2')
                    assert page.get_by_role('button',name='Save',exact=True).is_disabled()
                    page.get_by_role('button',name='factor-edit',exact=True).click()
                    page.get_by_label('Window',exact=True).fill('30')
                    page.get_by_role('switch',name='JSON parameters',exact=True).click()
                    assert json.loads(page.get_by_label('Parameters',exact=True).input_value())=={'N':'30'}
                    page.get_by_label('Parameters',exact=True).fill('{"N":30}')
                    page.get_by_role('button',name='Save',exact=True).click()
                    page.wait_for_function('window.saved.length===5')
                    edit=page.evaluate('window.calls.filter(c=>c.path.endsWith("/Alpha/factors")).at(-1).body')
                    assert edit['mode']=='edit' and edit['replace_factor_ref']=='factor:v2:a' and edit['params']=={'N':30}
                    page.get_by_role('button',name='category-edit',exact=True).click()
                    page.get_by_label('Entry name 1',exact=True).fill('Renamed')
                    assert page.get_by_label('Entry name 2',exact=True).is_disabled()
                    assert page.get_by_label('Product paths 2',exact=True).is_disabled()
                    page.get_by_role('button',name='Add entry',exact=True).click()
                    page.get_by_label('Entry name 3',exact=True).fill('Third')
                    page.get_by_label('Product paths 3',exact=True).fill('Product/C/')
                    page.get_by_role('button',name='Save',exact=True).click()
                    page.wait_for_function('window.saved.length===6')
                    category=page.evaluate('window.calls.filter(c=>c.path.includes("/categories/")).at(-1).body')
                    assert category['items'][0]['label']=='Renamed' and category['items'][2]['paths']==['Product/C/']
                    assert category['items'][1]['label_generated'] is True
                    page.get_by_role('button',name='composite-edit',exact=True).click()
                    assert page.get_by_label('Category name',exact=True).is_disabled()
                    assert page.get_by_label('Product paths 1',exact=True).is_disabled()
                    page.get_by_label('Entry name 1',exact=True).fill('Composite label')
                    assert page.get_by_role('button',name='Add entry',exact=True).count()==0
                    page.get_by_role('button',name='Save',exact=True).click()
                    page.wait_for_function('window.saved.length===7')
                    page.get_by_role('button',name='factor-nested',exact=True).click()
                    page.get_by_label('Nested Input type',exact=True).first.click()
                    page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter(has_text='Factor library').click()
                    page.evaluate('window.deferDetail=true')
                    page.get_by_role('combobox',name='Nested',exact=True).click()
                    page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter(has_text='Factor A').click()
                    page.wait_for_function('typeof window.releaseDetail==="function"')
                    expect(page.get_by_role('button',name='Save',exact=True)).to_be_disabled()
                    page.evaluate('window.releaseDetail()')
                    expect(page.get_by_role('button',name='Save',exact=True)).to_be_enabled()
                    page.get_by_role('button',name='Save',exact=True).click()
                    page.wait_for_function('window.saved.length===8')
                    nested=page.evaluate('window.calls.filter(c=>c.path.endsWith("/Alpha/factors")).at(-1).body.params.Child')
                    assert nested['ref']=='factor:v2:a' and nested['params']=={'N':20}
                    page.get_by_role('button',name='New factor',exact=True).click()
                    dialog=page.get_by_role('dialog')
                    dialog.wait_for()
                    assert page.locator('form form').count()==0
                    dialog.get_by_role('button',name='Cancel',exact=True).click()
                    dialog.wait_for(state='hidden')
                    parent_save=page.get_by_role('button',name=re.compile(r'^(loading )?Save$'))
                    expect(parent_save).to_be_enabled()
                    expect(parent_save).not_to_have_class(re.compile(r'ant-btn-loading(?: |$)'))


                    page.screenshot(path=f'/tmp/tr-factor-editors-{width}.png')
                    assert not errors
                    page.close()
            finally:browser.close()
    finally:server.shutdown();server.server_close();thread.join(timeout=5)
