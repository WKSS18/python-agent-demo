from pathlib import Path
from dotenv import dotenv_values
import oss2

root = Path(r'D:\python-agent-demo')
release = Path(r'D:\fieldnote-electron\release')
values = dotenv_values(root / '.env')
auth = oss2.Auth(values['OSS_ACCESS_KEY_ID'], values['OSS_ACCESS_KEY_SECRET'])
bucket = oss2.Bucket(auth, values['OSS_ENDPOINT'], values['OSS_BUCKET'])
files = {
    'releases/fieldnote/windows/fieldnote-desktop-1.0.1-x64.exe': release / 'fieldnote-desktop-1.0.1-x64.exe',
    'releases/fieldnote/windows/fieldnote-desktop-1.0.1-x64.exe.blockmap': release / 'fieldnote-desktop-1.0.1-x64.exe.blockmap',
    'releases/fieldnote/windows/app-icon.png': Path(r'D:\fieldnote-electron\build\icon.png'),
}
for key, path in files.items():
    headers = {'Content-Disposition': f'attachment; filename="{path.name}"'} if path.suffix != '.png' else {'Content-Type': 'image/png'}
    result = bucket.put_object_from_file(key, str(path), headers=headers)
    print(f'uploaded key={key} status={result.status} bytes={path.stat().st_size}')
print('acl=', bucket.get_bucket_acl().acl)
