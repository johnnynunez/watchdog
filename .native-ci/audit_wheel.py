"""Host-independent wheel integrity/architecture checks, no native execution."""
import base64,csv,hashlib,io,json,pathlib,struct,sys,zipfile
from email.parser import BytesParser

def pe(data):
    assert data[:2]==b'MZ', 'PE missing MZ'
    offset=struct.unpack_from('<I',data,0x3c)[0]
    assert data[offset:offset+4]==b'PE\0\0', 'PE signature'
    return struct.unpack_from('<H',data,offset+4)[0]

def audit(path, name, version):
    path=pathlib.Path(path)
    with zipfile.ZipFile(path) as z:
        names=z.namelist(); assert len(names)==len(set(names)), 'duplicate members'
        record=next(n for n in names if n.endswith('.dist-info/RECORD'))
        rows=list(csv.reader(io.StringIO(z.read(record).decode())))
        assert {r[0] for r in rows}==set(names), 'RECORD member coverage'
        for n,h,s in rows:
            if n==record: assert not h and not s; continue
            data=z.read(n); algo,digest=h.split('=',1)
            assert base64.urlsafe_b64encode(hashlib.new(algo,data).digest()).rstrip(b'=').decode()==digest, 'RECORD hash '+n
            assert len(data)==int(s), 'RECORD size '+n
        meta=BytesParser().parsebytes(z.read(next(n for n in names if n.endswith('.dist-info/METADATA'))))
        assert meta['Name'].lower()==name and meta['Version']==version, 'version/identity'
        assert path.name.endswith('win_arm64.whl'), 'wheel target'
        binaries={n:hex(pe(z.read(n))) for n in names if n.lower().endswith(('.pyd','.dll','.exe'))}
        assert all(m=='0xaa64' for m in binaries.values()), 'foreign PE architecture'
        assert len(binaries)=={'httptools':2,'psutil':1,'watchdog':0}[name], 'native payload count'
        return {'wheel':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'name':meta['Name'],'version':meta['Version'],'members':len(names),'record':'PASS','pe':binaries,'pure_windows_ctypes':name=='watchdog'}

if __name__=='__main__':
    print(json.dumps(audit(*sys.argv[1:]),indent=2))
