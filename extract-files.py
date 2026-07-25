#!/usr/bin/env -S PYTHONPATH=../../../tools/extract-utils python3
#
# SPDX-FileCopyrightText: 2016 The CyanogenMod Project
# SPDX-FileCopyrightText: 2017-2024 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#

import re
from pathlib import Path

from extract_utils.fixups_lib import (
    lib_fixups,
    lib_fixups_user_type,
)
from extract_utils.fixups_blob import (
    blob_fixup,
    blob_fixups_user_type,
)
from extract_utils.main import (
    ExtractUtils,
    ExtractUtilsModule,
)
from extract_utils.tools import (
    apktool_path,
    java_path,
)
from extract_utils.utils import run_cmd


def lib_fixup_system_ext_suffix(lib: str, partition: str, *args, **kwargs):
    """
    Mirrors lib_to_package_fixup_system_ext_variants from the old setup-makefiles.sh.
    These libs exist as system_ext variants and need a _system_ext suffix
    when pulled from that partition.
    """
    if partition != 'system_ext':
        return None

    system_ext_libs = {
        'libSuperTextWrapper',
        'libXDocProcessSDK',
        'libYTCommon',
        'libmpbase',
        'libextendfile',
    }

    return f'{lib}_system_ext' if lib in system_ext_libs else None


lib_fixups: lib_fixups_user_type = {
    # **lib_fixups already includes the clang RT ubsan and proto 3.9.1
    # fixups that were previously handled by the bash helper functions
    # lib_to_package_fixup_clang_rt_ubsan_standalone and
    # lib_to_package_fixup_proto_3_9_1 — no need to add them explicitly.
    **lib_fixups,
    (
        'libSuperTextWrapper',
        'libXDocProcessSDK',
        'libYTCommon',
        'libmpbase',
        'libextendfile',
    ): lib_fixup_system_ext_suffix,
}


def _replace_smali_method(data: str, signature: str, body: str) -> str:
    return re.sub(
        rf'(?ms)^\.method {re.escape(signature)}\n.*?^\.end method',
        f'.method {signature}\n{body}.end method',
        data,
        count=1,
    )


def blob_fixup_apktool_unpack_src(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    run_cmd([
        java_path,
        '-Xmx8g',
        '-jar',
        apktool_path,
        'd',
        file_path,
        '-o',
        tmp_dir,
        '-f',
        '--no-res',
    ])


def blob_fixup_aiunit_baseos_empty(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    # Avoid ClassNotFoundException for com.oplus.cust.OplusCfgFilePolicy on non-OOS.
    # Stub also lives in hardware/oplus/oplus-fwk; this is belt-and-suspenders.
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / (
        'smali_classes2/com/oplus/aiunit/configuration/data/assets/'
        'BaseOSLoadStrategy.smali'
    )
    if not smali.exists():
        return

    body = (
        '    .locals 1\n'
        '\n'
        '    invoke-static {}, Ljava/util/Collections;->emptyMap()Ljava/util/Map;\n'
        '\n'
        '    move-result-object v0\n'
        '\n'
        '    return-object v0\n'
    )
    data = smali.read_text(encoding='utf-8')
    fixed = _replace_smali_method(
        data,
        'public final listFilesFromOS(Landroid/content/Context;Ljava/lang/String;Ljava/lang/String;)Ljava/util/Map;',
        body,
    )
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')


def blob_fixup_aiunit_authorize_camera(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    # Whitelist com.oplus.camera + com.oneplus.gallery for AIUnit authorize().
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali_classes2/com/oplus/aiunit/core/AIUnitServiceBinder.smali'
    if not smali.exists():
        return

    data = smali.read_text(encoding='utf-8')
    old = (
        '    :goto_2\n'
        '    new-instance v10, Ljava/lang/StringBuilder;\n'
    )
    new = (
        '    :goto_2\n'
        '    const-string v10, "com.oplus.camera"\n'
        '\n'
        '    invoke-static {v5, v10}, Lkotlin/jvm/internal/Intrinsics;->areEqual(Ljava/lang/Object;Ljava/lang/Object;)Z\n'
        '\n'
        '    move-result v10\n'
        '\n'
        '    if-nez v10, :cond_oplus_aiunit_trusted_auth\n'
        '\n'
        '    const-string v10, "com.oneplus.gallery"\n'
        '\n'
        '    invoke-static {v5, v10}, Lkotlin/jvm/internal/Intrinsics;->areEqual(Ljava/lang/Object;Ljava/lang/Object;)Z\n'
        '\n'
        '    move-result v10\n'
        '\n'
        '    if-eqz v10, :cond_oplus_aiunit_auth\n'
        '\n'
        '    :cond_oplus_aiunit_trusted_auth\n'
        '    const/4 v9, 0x1\n'
        '\n'
        '    :cond_oplus_aiunit_auth\n'
        '    new-instance v10, Ljava/lang/StringBuilder;\n'
    )
    marker = '    const-string v12, "authorize "\n'
    idx = data.find(marker)
    if idx < 0:
        return
    chunk_start = data.rfind(old, 0, idx)
    if chunk_start < 0:
        return
    fixed = data[:chunk_start] + new + data[chunk_start + len(old) :]
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')

    provider = Path(tmp_dir) / 'smali_classes2/com/oplus/aiunit/AIUnitProvider.smali'
    if not provider.exists():
        return
    pdata = provider.read_text(encoding='utf-8')
    m = re.search(r'(?ms)^\.method public final e\(\)Z\n.*?^\.end method', pdata)
    if not m:
        return
    method = m.group(0)
    pold = (
        '    :cond_0\n'
        '    invoke-virtual {p0}, Lcom/oplus/aiunit/base/component/BaseContentProvider;->a()Landroid/content/Context;\n'
    )
    pnew = (
        '    :cond_0\n'
        '    const-string v1, "com.oplus.camera"\n'
        '\n'
        '    invoke-static {v0, v1}, Lkotlin/jvm/internal/Intrinsics;->areEqual(Ljava/lang/Object;Ljava/lang/Object;)Z\n'
        '\n'
        '    move-result v1\n'
        '\n'
        '    if-nez v1, :cond_oplus_aiunit_provider_trusted\n'
        '\n'
        '    const-string v1, "com.oneplus.gallery"\n'
        '\n'
        '    invoke-static {v0, v1}, Lkotlin/jvm/internal/Intrinsics;->areEqual(Ljava/lang/Object;Ljava/lang/Object;)Z\n'
        '\n'
        '    move-result v1\n'
        '\n'
        '    if-eqz v1, :cond_oplus_aiunit_provider_check\n'
        '\n'
        '    :cond_oplus_aiunit_provider_trusted\n'
        '    const/4 p0, 0x1\n'
        '\n'
        '    return p0\n'
        '\n'
        '    :cond_oplus_aiunit_provider_check\n'
        '    invoke-virtual {p0}, Lcom/oplus/aiunit/base/component/BaseContentProvider;->a()Landroid/content/Context;\n'
    )
    if pold not in method:
        return
    method2 = method.replace(pold, pnew, 1)
    provider.write_text(pdata[: m.start()] + method2 + pdata[m.end() :], encoding='utf-8')


def blob_fixup_aiunit_plugin_so_permissions(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali_classes2/com/oplus/orange/utils/FileUtil.smali'
    if not smali.exists():
        return
    data = smali.read_text(encoding='utf-8')
    old = (
        '    invoke-static {v2, v9, v10}, Lcom/oplus/orange/utils/FileUtil;->unzip(Ljava/util/zip/ZipFile;Ljava/util/zip/ZipEntry;Ljava/io/File;)V\n'
        '\n'
        '    .line 218\n'
        '    .line 219\n'
        '    .line 220\n'
        '    const/4 v9, 0x0\n'
    )
    new = (
        '    invoke-static {v2, v9, v10}, Lcom/oplus/orange/utils/FileUtil;->unzip(Ljava/util/zip/ZipFile;Ljava/util/zip/ZipEntry;Ljava/io/File;)V\n'
        '\n'
        '    const/4 v9, 0x1\n'
        '\n'
        '    invoke-virtual {v10, v9}, Ljava/io/File;->setReadable(Z)Z\n'
        '\n'
        '    invoke-virtual {v10, v9}, Ljava/io/File;->setExecutable(Z)Z\n'
        '\n'
        '    .line 218\n'
        '    .line 219\n'
        '    .line 220\n'
        '    const/4 v9, 0x0\n'
    )
    fixed = data.replace(old, new, 1)
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')


def blob_fixup_stdid_receiver_flags(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    # A14+ requires RECEIVER_EXPORTED / RECEIVER_NOT_EXPORTED.
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali/com/oplus/stdid/AppApplication.smali'
    if not smali.exists():
        return

    new_method = '''.method public final onCreate()V
    .locals 7

    invoke-super {p0}, Landroid/app/Application;->onCreate()V

    sget-object v0, Lq0/b;->b:Lq0/b;

    const/4 v6, 0x0

    if-nez v0, :cond_0

    new-instance v0, Lq0/b;

    invoke-direct {v0}, Ljava/lang/Object;-><init>()V

    iput-object v6, v0, Lq0/b;->a:Ljava/lang/String;

    sput-object v0, Lq0/b;->b:Lq0/b;

    :cond_0
    sget-object v0, Lq0/b;->b:Lq0/b;

    invoke-virtual {v0, p0}, Lq0/b;->a(Landroid/content/Context;)V

    new-instance v2, Landroid/content/IntentFilter;

    invoke-direct {v2}, Landroid/content/IntentFilter;-><init>()V

    const-string v0, "oplus.intent.action.PACKAGE_REMOVED"

    invoke-virtual {v2, v0}, Landroid/content/IntentFilter;->addAction(Ljava/lang/String;)V

    const-string v0, "package"

    invoke-virtual {v2, v0}, Landroid/content/IntentFilter;->addDataScheme(Ljava/lang/String;)V

    const-string v3, "oplus.permission.OPLUS_COMPONENT_SAFE"

    invoke-static {v3}, Landroid/text/TextUtils;->isEmpty(Ljava/lang/CharSequence;)Z

    move-result v0

    iget-object v1, p0, Lcom/oplus/stdid/AppApplication;->a:Lp0/a;

    const/4 v5, 0x4

    if-eqz v0, :cond_1

    invoke-virtual {p0, v1, v2, v5}, Landroid/content/Context;->registerReceiver(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;I)Landroid/content/Intent;

    goto :goto_0

    :cond_1
    move-object v0, p0
    move-object v4, v6
    invoke-virtual/range {v0 .. v5}, Landroid/content/Context;->registerReceiver(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;Ljava/lang/String;Landroid/os/Handler;I)Landroid/content/Intent;

    :goto_0
    return-void
.end method
'''
    data = smali.read_text(encoding='utf-8')
    fixed, n = re.subn(
        r'(?ms)^\.method public final onCreate\(\)V\n.*?^\.end method',
        new_method,
        data,
        count=1,
    )
    if n:
        smali.write_text(fixed, encoding='utf-8')



def blob_fixup_aiunit_disable_settings(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    """Keep AIUnit for Camera/Gallery; do not inject into system Settings."""
    if tmp_dir is None:
        return
    try:
        import pyaxml
    except ImportError:
        return
    manifest = Path(tmp_dir) / 'AndroidManifest.xml'
    # With --no-res unpack, manifest may be binary under original/ or decoded text.
    candidates = [
        manifest,
        Path(tmp_dir) / 'original' / 'AndroidManifest.xml',
    ]
    # Prefer binary from the apk itself when unpack used --no-res leaves decoded?
    target = None
    for c in candidates:
        if c.exists() and c.stat().st_size > 0:
            # binary AXML starts with 0x00080003 little-endian magic often
            head = c.read_bytes()[:4]
            if head[:2] == b'\x03\x00' or head == b'\x03\x00\x08\x00' or head[0] != ord('<'):
                target = c
                break
    if target is None:
        # fall back: patch text manifest if present
        if manifest.exists() and manifest.read_text(encoding='utf-8', errors='ignore').lstrip().startswith('<'):
            data = manifest.read_text(encoding='utf-8')
            data = data.replace(
                'android:authorities="com.oplus.aiunit.search" android:exported="true"',
                'android:authorities="com.oplus.aiunit.search" android:enabled="false" android:exported="false"',
            )
            data = data.replace(
                'android:authorities="com.oplus.aiunit.authority.settings.switch" android:exported="true"',
                'android:authorities="com.oplus.aiunit.authority.settings.switch" android:enabled="false" android:exported="false"',
            )
            data = data.replace(
                'android:name="ai::meta::enable_settings_ui" android:value="true"',
                'android:name="ai::meta::enable_settings_ui" android:value="false"',
            )
            data = data.replace(
                'android:name="ai::meta::enable_local_llm_settings_ui" android:value="true"',
                'android:name="ai::meta::enable_local_llm_settings_ui" android:value="false"',
            )
            manifest.write_text(data, encoding='utf-8')
        return

    axml = pyaxml.AXML.from_axml(target.read_bytes())
    root = axml.to_xml()
    NS = '{http://schemas.android.com/apk/res/android}'

    def get_a(el, name):
        for k, v in el.attrib.items():
            if k == name or k.endswith('}' + name) or k.endswith(':' + name):
                return v
        return None

    def set_a(el, name, value):
        for k in list(el.attrib):
            if k == name or k.endswith('}' + name) or k.endswith(':' + name):
                el.attrib[k] = value
                return
        el.attrib[NS + name] = value

    app = next(e for e in root.iter() if e.tag.split('}')[-1] == 'application')
    for prov in list(app):
        if prov.tag.split('}')[-1] != 'provider':
            continue
        auth = get_a(prov, 'authorities') or ''
        name = get_a(prov, 'name') or ''
        # Must remove: OplusSearchIndexablesProvider.attachInfo requires exported,
        # and exported providers re-inject into Settings.
        if auth in (
            'com.oplus.aiunit.search',
            'com.oplus.aiunit.authority.settings.switch',
        ) or 'AIUnitSearchIndexProvider' in name or 'AIUnitSettingsSwitchProvider' in name:
            app.remove(prov)
    for meta in [e for e in app if e.tag.split('}')[-1] == 'meta-data']:
        name = get_a(meta, 'name') or ''
        if name in (
            'ai::meta::enable_settings_ui',
            'ai::meta::enable_local_llm_settings_ui',
        ):
            set_a(meta, 'value', 'false')
    for act in [e for e in app if e.tag.split('}')[-1] == 'activity']:
        name = get_a(act, 'name') or ''
        if name not in (
            'com.oplus.aiunit.settings.AIUnitSettingsActivity',
            'com.oplus.aiunit.settings.ExpAIStrengthenActivity',
        ):
            continue
        set_a(act, 'exported', 'false')
        for child in list(act):
            tag = child.tag.split('}')[-1]
            if tag == 'intent-filter':
                blob = ' '.join(
                    filter(None, (get_a(sub, 'name') for sub in child.iter()))
                )
                if 'MANUFACTURER_APPLICATION_SETTING' in blob:
                    act.remove(child)
            elif tag == 'meta-data':
                mname = get_a(child, 'name') or ''
                if mname.startswith('com.android.settings.') or mname.startswith(
                    'com.oplus.settings.'
                ):
                    act.remove(child)
    new = pyaxml.AXML()
    new.from_xml(root)
    target.write_bytes(new.pack())


blob_fixups: blob_fixups_user_type = {
    'system_ext/priv-app/OplusCamera/OplusCamera.apk': blob_fixup()
        .apktool_patch('patches'),
    'system_ext/framework/com.oplus.camera.unit.sdk.jar': blob_fixup()
        .apktool_patch('patches-sdk'),
    'system_ext/priv-app/OppoGallery2/OppoGallery2.apk': blob_fixup()
        .apktool_patch('patches-gallery'),
    'system_ext/priv-app/AIUnit/AIUnit.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_src)
        .call(blob_fixup_aiunit_disable_settings)
        .call(blob_fixup_aiunit_baseos_empty)
        .call(blob_fixup_aiunit_authorize_camera)
        .call(blob_fixup_aiunit_plugin_so_permissions)
        .apktool_pack()
        .stripzip(),
    'system_ext/priv-app/StdID/StdID.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_src)
        .call(blob_fixup_stdid_receiver_flags)
        .apktool_pack()
        .stripzip(),
    'odm/etc/init/init.camera_process.rc': blob_fixup()
        .regex_replace(
            '''on post-fs-data
    mkdir /data/vendor/camera_process 0777 camera camera
    mkdir /data/vendor/camera_process/livephoto 0777 camera camera
    mkdir /data/vendor/cam_alog 0777 camera camera
on property:sys.camera.user.removed=*
    #delete_recursion /data/vendor/camera_process/${sys.camera.user.removed}
''',
            '''on post-fs-data
    mkdir /data/vendor/camera_process 0777 camera camera
    mkdir /data/vendor/camera_process/livephoto 0777 camera camera
    mkdir /data/vendor/cam_alog 0777 camera camera
    # APS file storage for deferred-capture jobs (matches stock init.oplus.rootdir.rc).
    # Without these, APSFileStorage can't mkdir under system-owned /data/system,
    # defer-job params are never persisted (keepJob "Not found in FileSystem"),
    # and the offline metadata collapses to empty -> photo-capture crash.
    mkdir /data/system/camera_rus 0777 cameraserver cameraserver
    mkdir /data/vendor/camera_rus 0777 camera camera
on property:sys.camera.user.removed=*
    #delete_recursion /data/vendor/camera_process/${sys.camera.user.removed}
''',
        )
}  # fmt: skip

namespace_imports = [
    'vendor/oplus/camera/camera',
    'vendor/oneplus/dodge',
    'vendor/oneplus/sm8750-common',
    'hardware/oplus',
]

module = ExtractUtilsModule(
    'camera',
    'oplus/camera',
    device_rel_path='vendor/oplus/camera',
    blob_fixups=blob_fixups,
    lib_fixups=lib_fixups,
    namespace_imports=namespace_imports,
)

if __name__ == '__main__':
    utils = ExtractUtils.device(module)
    utils.run()
