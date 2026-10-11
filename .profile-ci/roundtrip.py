"""Real installed WindowsApiObserver events and bounded owned-thread teardown."""
import hashlib, importlib.metadata, json, os, pathlib, platform, queue, struct, sys, sysconfig, tempfile, threading, time
import watchdog
from watchdog.events import FileSystemEventHandler
from watchdog.observers.read_directory_changes import WindowsApiObserver

def pe(path):
    data=pathlib.Path(path).read_bytes(); offset=struct.unpack_from('<I',data,0x3c)[0]
    assert data[offset:offset+4]==b'PE\0\0'
    return hex(struct.unpack_from('<H',data,offset+4)[0])
def snapshot(): return [{'name':t.name,'ident':t.ident,'alive':t.is_alive(),'daemon':t.daemon} for t in threading.enumerate()]
result={'version':importlib.metadata.version('watchdog'),'module':watchdog.__file__,'python':sys.version,'platform':sysconfig.get_platform(),'interpreter_pe':pe(sys.executable),'base_interpreter_pe':pe(sys._base_executable),'machine':platform.machine(),'cycles':[]}
assert result['version']=='4.0.0' and 'site-packages' in watchdog.__file__
expected='0xaa64' if sysconfig.get_platform()=='win-arm64' else '0x8664'
assert result['interpreter_pe']==result['base_interpreter_pe']==expected
for cycle in range(10):
    before=set(threading.enumerate()); events=[]; q=queue.Queue()
    class Handler(FileSystemEventHandler):
        def on_any_event(self,event): q.put(event)
    with tempfile.TemporaryDirectory() as d:
        root=pathlib.Path(d); obs=WindowsApiObserver(timeout=0.1)
        obs.schedule(Handler(),d,recursive=True); obs.start(); emitters=list(obs.emitters)
        def take(event_type,src,dst=None,timeout=5):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                e=q.get(timeout=max(0.01,deadline-time.monotonic()))
                rec={'type':e.event_type,'src':os.path.relpath(e.src_path,d),'dest':os.path.relpath(e.dest_path,d) if e.dest_path else '', 'directory':e.is_directory,'synthetic':e.is_synthetic}
                events.append(rec)
                if e.event_type==event_type and e.src_path==str(src) and (dst is None or e.dest_path==str(dst)): return
            raise AssertionError((event_type,src,dst,events))
        try:
            a=root/'a'; b=a/'b'; a.mkdir(); take('created',a); b.mkdir(); take('created',b)
            # Record the same event gap as the legacy expectation, without inventing an event.
            time.sleep(0.25)
            gap=[]
            while not q.empty():
                e=q.get_nowait(); gap.append({'type':e.event_type,'src':os.path.relpath(e.src_path,d)})
            a2=root/'a2'; a.rename(a2); take('moved',a,a2); take('moved',b,a2/'b')
            f=a2/'b'/'file'; g=a2/'b'/'renamed'
            f.write_text('one'); take('created',f)
            with f.open('a') as stream: stream.write('two'); stream.flush(); os.fsync(stream.fileno())
            take('modified',f); f.rename(g); take('moved',f,g); g.unlink(); take('deleted',g)
        finally:
            obs.stop(); obs.join(5)
            for emitter in emitters: emitter.join(5)
        assert not obs.is_alive() and not any(e.is_alive() for e in emitters)
        assert set(threading.enumerate())==before, snapshot()
        result['cycles'].append({'cycle':cycle,'events':events,'after_subdir_create_gap':gap,'threads_after':snapshot(),'observer_stopped':True,'emitters_stopped':True})
result['status']='PASS'
pathlib.Path(sys.argv[1]).write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
