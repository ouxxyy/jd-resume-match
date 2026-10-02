"""合成案例浏览器验收。仓库根目录运行；仅用标准库和临时 Chrome 配置。"""
import sys,subprocess,time,json,urllib.request,tempfile,base64,shutil
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'scripts'))
import export_png as ep
port=ep.free_port();profile=tempfile.mkdtemp(prefix='jd-strategy-visual-')
proc=subprocess.Popen([ep.find_browser(None),'--headless=new','--disable-gpu','--hide-scrollbars','--no-first-run','--no-default-browser-check',f'--remote-debugging-port={port}','--user-data-dir='+profile,'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
ws=None;out=Path('docs/strategy-upgrade');out.mkdir(exist_ok=True)
try:
 for _ in range(80):
  time.sleep(.2)
  try:
   ts=json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list',timeout=2));url=next(t['webSocketDebuggerUrl'] for t in ts if t.get('type')=='page');break
  except Exception:pass
 else:raise RuntimeError('Chrome 未就绪')
 ws=ep.WSClient('127.0.0.1',port,url.split(str(port),1)[1]);cdp=ep.CDPSession(ws);cdp.call('Page.enable')
 def js(expression):return cdp.call('Runtime.evaluate',{'expression':expression,'awaitPromise':True,'returnByValue':True})['result'].get('value')
 checks=[]
 for case,width in [(case,width) for case in ["education-first-work","older-relevant-work","freshgrad-project","freshgrad-project-research"] for width in [1440,390]]:
  cdp.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':1000,'deviceScaleFactor':1,'mobile':False})
  path=(Path('examples/strategy-upgrade')/case/'preview/report.html').resolve()
  cdp.call('Page.navigate',{'url':path.as_uri()});time.sleep(.5)
  result=js('JSON.stringify({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,strategyBeforeRewrite:document.getElementById("section-strategy").compareDocumentPosition(document.getElementById("section-rewrites"))===4,detailClosed:!document.querySelector("#section-strategy details.details-accordion").open,nav:document.querySelectorAll(".toc-link").length})')
  result=json.loads(result);assert result['scrollWidth']<=width,result;assert result['strategyBeforeRewrite'] and result['detailClosed'];assert result['nav']==6
  js('document.querySelector("#section-strategy details.details-accordion summary").click();new Promise(r=>setTimeout(r,50))');assert js('document.querySelector("#section-strategy details.details-accordion").open')
  js('document.querySelector("#section-strategy details.details-accordion summary").click();document.querySelector("a[href=\\"#section-strategy\\"]").click();new Promise(r=>setTimeout(r,50))');assert js('location.hash')=='#section-strategy'
  js('Object.defineProperty(navigator,"clipboard",{value:{writeText:async t=>{window.__copied=t}},configurable:true});document.querySelector("[data-copy]").click();new Promise(r=>setTimeout(r,50))')
  assert '保留原任职日期' in js('window.__copied');assert js('document.querySelector("[data-copy]").textContent')=='已复制 ✓'
  shot=cdp.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True});(out/f'{case}-report-{width}.png').write_bytes(base64.b64decode(shot['data']))
  crop=cdp.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False});(out/f'{case}-structure-{width}.png').write_bytes(base64.b64decode(crop['data']))
  result.update(case=case,expand=True,navigation=True,copy_handler=True);checks.append(result)
 cdp.call('Emulation.setDeviceMetricsOverride',{'width':1080,'height':1440,'deviceScaleFactor':1,'mobile':False})
 cdp.call('Page.navigate',{'url':Path('examples/strategy-upgrade/education-first-work/preview/member-card-01.html').resolve().as_uri()});time.sleep(.5)
 shot=cdp.call('Page.captureScreenshot',{'format':'png'});(out/'member-card-01.png').write_bytes(base64.b64decode(shot['data']))
 (out/'browser-checks.json').write_text(json.dumps({'synthetic':True,'private_markers':['合成机构甲','合成院校'],'checks':checks},ensure_ascii=False,indent=2)+'\n');print(json.dumps(checks,ensure_ascii=False));print('报告截图及 1080×1440 成员卡已导出')
finally:
 if ws:ws.close()
 proc.terminate()
 try:proc.wait(timeout=5)
 except subprocess.TimeoutExpired:proc.kill();proc.wait()
 shutil.rmtree(profile,ignore_errors=True)
