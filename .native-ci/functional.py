"""Real installed-wheel oracles. Only private temp files and owned children."""
import importlib,importlib.metadata,json,os,pathlib,platform,queue,subprocess,sys,sysconfig,tempfile,time
from audit_wheel import pe
name,version,output=sys.argv[1:]
assert sys.platform=='win32' and sysconfig.get_platform()=='win-arm64'
assert sys.version_info[:2]==(3,12)
assert pe(pathlib.Path(sys.executable).read_bytes())==0xaa64
module=importlib.import_module(name)
assert 'site-packages' in module.__file__.lower(),module.__file__
assert importlib.metadata.version(name)==version
result={'package':name,'version':version,'python':sys.version,'interpreter':sys.executable,'interpreter_pe':'0xaa64','platform':sysconfig.get_platform(),'module':module.__file__}
if name=='httptools':
    class Protocol:
        def __init__(self):self.url=b'';self.body=b'';self.headers=[];self.complete=0
        def on_url(self,u):self.url+=u
        def on_header(self,k,v):self.headers.append((k,v))
        def on_body(self,b):self.body+=b
        def on_message_complete(self):self.complete+=1
    p=Protocol(); parser=module.HttpRequestParser(p)
    wire=b'POST /native?q=arm64 HTTP/1.1\r\nHost: localhost\r\nContent-Length: 5\r\n\r\nhello'
    for i in range(0,len(wire),3):parser.feed_data(wire[i:i+3])
    assert p.complete==1 and p.url==b'/native?q=arm64' and p.body==b'hello'
    assert parser.get_method()==b'POST' and parser.get_http_version()=='1.1'
    r=Protocol(); response=module.HttpResponseParser(r)
    response.feed_data(b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nworld\r\n0\r\n\r\n')
    assert response.get_status_code()==200 and r.body==b'world' and r.complete==1
    assert module.parse_url(b'http://localhost:8080/native?q=arm64').port==8080
    try:module.HttpRequestParser(Protocol()).feed_data(b'BAD METHOD / HTTP/1.1\r\n\r\n')
    except module.HttpParserError:pass
    else:raise AssertionError('malformed request accepted')
    result['functional']=['fragmented POST body/header/request','chunked response','URL port','malformed request rejected']
elif name=='psutil':
    import psutil
    owner=psutil.Process(); before=owner.num_handles()
    script="import os,sys; payload=bytearray(1024*1024); print(os.getpid(),flush=True); sys.stdin.readline(); sys.exit(7)"
    p=subprocess.Popen([sys.executable,'-c',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    try:
        assert int(p.stdout.readline())==p.pid
        child=psutil.Process(p.pid)
        assert child.ppid()==os.getpid() and child.is_running()
        with child.oneshot():
            assert child.memory_info().rss>0
            assert child.num_threads()>=1 and child.num_handles()>0
            assert pathlib.Path(child.exe()).resolve()==pathlib.Path(sys.executable).resolve()
            assert child.cpu_times().user>=0
        assert any(x.pid==p.pid for x in owner.children())
        for _ in range(200):
            assert child.memory_info().rss>0; child.cpu_times();child.num_handles()
        during=owner.num_handles()
        assert during-before<20,(before,during)
        try:child.wait(timeout=0.01)
        except psutil.TimeoutExpired:pass
        else:raise AssertionError('child unexpectedly exited')
        p.stdin.write('exit\n');p.stdin.flush()
        assert p.wait(timeout=10)==7
        assert child.wait(timeout=5)==7
        try:child.memory_info()
        except psutil.NoSuchProcess:pass
        else:raise AssertionError('dead child accepted')
    finally:
        if p.poll() is None:p.kill();p.wait(timeout=5)
        p.stdin.close();p.stdout.close()
    result['functional']=['owned child identity/ppid/exe','memory/threads/CPU/handles','timeout','exit=7','NoSuchProcess negative']
    result['handles']={'before':before,'during':during,'after':owner.num_handles(),'repeated_queries':200}
else:
    from watchdog.observers import Observer
    from watchdog.observers.read_directory_changes import WindowsApiObserver
    from watchdog.events import FileSystemEventHandler
    assert Observer is WindowsApiObserver
    events=queue.Queue()
    class Handler(FileSystemEventHandler):
        def on_any_event(self,event):events.put((event.event_type,event.src_path,getattr(event,'dest_path',None)))
    captured=[]
    def wait(kind,path):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            try:e=events.get(timeout=.2)
            except queue.Empty:continue
            captured.append(e)
            if e[0]==kind and os.path.normcase(e[1])==os.path.normcase(str(path)):return e
        raise AssertionError((kind,str(path),captured))
    with tempfile.TemporaryDirectory(prefix='watchdog-native-') as td:
        root=pathlib.Path(td); observer=Observer(timeout=.1); observer.schedule(Handler(),td,recursive=True);observer.start()
        try:
            a=root/'roundtrip.txt';b=root/'renamed.txt'
            a.write_text('native');wait('created',a)
            a.write_text('native changed');wait('modified',a)
            a.rename(b);event=wait('moved',a);assert os.path.normcase(event[2])==os.path.normcase(str(b))
            b.unlink();wait('deleted',b)
            assert not (root/'never-created').exists()
        finally:observer.stop();observer.join(timeout=10)
        assert not observer.is_alive()
    result['functional']=['ReadDirectoryChangesW create/modify/rename/delete','observer teardown']
    result['events']=captured
result['status']='PASS'
pathlib.Path(output).write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
