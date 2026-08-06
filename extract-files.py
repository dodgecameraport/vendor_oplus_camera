#!/usr/bin/env -S PYTHONPATH=../../../tools/extract-utils python3
#
# SPDX-FileCopyrightText: 2016 The CyanogenMod Project
# SPDX-FileCopyrightText: 2017-2024 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#

import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
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


# <kind>-<unitName>-<unitId>-<unitVersion>[-<variant>][.apk]
AIUNIT_PACK_RE = re.compile(
    r'^(?P<kind>plugin|engine|detector|oaa|oap)-'
    r'(?P<name>.+?)-(?P<id>\d+)-(?P<ver>\d+)(?:-.*?)?(?:\.apk)?$'
)


def blob_fixup_aiunit_preinstall_packs(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    # Ship the Gallery AI edit plugins inside AIUnit's own assets so they are
    # preinstalled offline instead of being fetched from the CDN at first use.
    #
    # AIUnit has several unit load strategies. The OS ones (BaseOSLoadStrategy,
    # OsLegacy/OsOap2) read the stock my_product/etc/aisubsystem preload dir via
    # com.oplus.cust.OplusCfgFilePolicy, which does not exist off OOS -- that is
    # exactly what blob_fixup_aiunit_baseos_empty stubs out. ApkAssetsLoadStrategy
    # is the only one left working, and it is already how the bundled OCR engines
    # and image_scan_code get installed, so we ride that path.
    #
    # A pack is only picked up if it is ALSO registered in two separate files,
    # and unit_config_list.json is only one of them. Orange.json is the version
    # and integrity registry:
    #
    #   {"id": 185618451, "version": 1014,
    #    "fileName": "Plugin/plugin-image_scan_code-185618451-1014.apk",
    #    "fileSize": 16479081, "fileHash": "<sha256>", "type": ".apk",
    #    "subDir": "Plugin", "autoUninstall": false}
    #
    # AssetsUnitStore only unpacks an asset into app_preinstalled/ if it has a
    # record here, and LocalUnitStore.getConfigurationVersion() reads its version
    # back. With no record the version comes out -1, isLocalFileValid() is then
    # false regardless of the file being present, and UnitRouter parks the unit at
    # state 6 / kErrorNoDownload:
    #
    #   UnitRouter: updateWrapperWithFileStatus, local file
    #     DependConfig(id=185622541, strict=true), invalid, version: -1
    #
    # Measured on device before this was added: of the 13 plugins in assets only
    # image_scan_code -- the single one carrying a stock Orange record -- had been
    # unpacked into app_preinstalled/Plugin. The installed count matched the
    # has-a-record count exactly in every subdirectory (Plugin 1/1, Engine 15/15,
    # Detector 10/10, OAA 1/1, OAP 1/1), and all 19 packs shipped in aiunit-packs
    # were in the no-record set. None of them had ever installed.
    if tmp_dir is None:
        return

    packs_root = Path(__file__).parent / 'aiunit-packs'
    if not packs_root.is_dir():
        return

    assets = Path(tmp_dir) / 'assets'
    unit_config = assets / 'unit_config_list.json'
    if not unit_config.exists():
        return

    units = json.loads(unit_config.read_text(encoding='utf-8'))
    by_id = {u.get('unitId'): u for u in units if isinstance(u, dict)}

    orange_config = assets / 'Orange.json'
    orange = (
        json.loads(orange_config.read_text(encoding='utf-8'))
        if orange_config.exists()
        else []
    )
    orange_added = []

    # Plugin/, Engine/, Detector/ -- mirrors the layout AIUnit already ships.
    for kind_dir in sorted(p for p in packs_root.iterdir() if p.is_dir()):
        dest = assets / kind_dir.name
        dest.mkdir(parents=True, exist_ok=True)

        for pack in sorted(kind_dir.iterdir()):
            match = AIUNIT_PACK_RE.match(pack.name)
            if match is None:
                continue

            shutil.copy2(pack, dest / pack.name)

            unit_id = int(match.group('id'))
            unit_version = int(match.group('ver'))

            # fileHash is a plain sha256 of the file and fileSize its byte count
            # -- verified against every stock record whose asset is actually
            # shipped, 12 of 12 matched. The remaining stock records describe
            # engines that get downloaded rather than bundled.
            payload = pack.read_bytes()
            orange_added.append(
                {
                    'id': unit_id,
                    'version': unit_version,
                    'fileName': f'{kind_dir.name}/{pack.name}',
                    'fileSize': len(payload),
                    'fileHash': hashlib.sha256(payload).hexdigest(),
                    'type': '.apk' if pack.suffix == '.apk' else '.zip',
                    'subDir': kind_dir.name,
                    'autoUninstall': False,
                }
            )

            unit = by_id.get(unit_id)
            if unit is None:
                # Engines are referenced by id from the detector manifests and
                # are not listed individually, so only plugins need an entry
                # invented for them.
                if match.group('kind') != 'plugin':
                    continue
                unit = {
                    'unitName': match.group('name'),
                    'unitId': unit_id,
                    'unitType': 'Plugin',
                }
                units.append(unit)
                by_id[unit_id] = unit

            # Keep the declared version in sync with the pack we actually ship,
            # and make sure nothing we bundle is left switched off.
            unit['unitVersion'] = unit_version
            unit['disabled'] = False

            # preinstallWithUnit is what decides whether a unit is installed
            # from assets: on device the only units that landed were the ones
            # carrying it, and their engines came along as dependencies.
            # Without it the pack ships inside the APK and is never unpacked.
            unit['preinstall'] = True
            unit['preinstallWithUnit'] = True

            # The stock list can name engines from an older revision of a
            # detector -- image_interactive_seg_qcom v1 wants 235929687 while
            # the v2 pack wants 235929684. Trust the pack we actually ship, or
            # AIUnit resolves a dependency that is not there.
            if match.group('kind') == 'detector':
                with zipfile.ZipFile(pack) as z:
                    manifest = json.loads(z.read('manifest.json'))
                for key in ('engines', 'optEngines'):
                    if key in manifest:
                        unit[key] = manifest[key]

    unit_config.write_text(json.dumps(units, indent=2), encoding='utf-8')

    # Ours win for any id already described: the record has to name the file that
    # is actually in assets, and where we ship a pack that is what is there. Stock
    # repeats some engine ids verbatim (AIUnit dedupes on load, and the device
    # copy comes back with 28 records for the 39 in assets), so dropping every
    # record for an id we are replacing loses nothing.
    replaced = {record['id'] for record in orange_added}
    orange = [
        record
        for record in orange
        if not (isinstance(record, dict) and record.get('id') in replaced)
    ]
    orange.extend(orange_added)
    orange_config.write_text(json.dumps(orange, indent=2), encoding='utf-8')


# ConfigAbilityWrapper flags that gate the AI entries in the Gallery editor.
# 0005 already forces the olive* ones for Live Photo; these are the rest.
GALLERY_AI_FEATURE_FLAGS = (
    'feature_is_support_beauty_entrance',
    'feature_is_support_ipu_filter',
    # Not AI entries -- these two are the editor's HDR capability, and without
    # them Perfect Shot's face picker comes back empty. See the note below.
    'feature_is_support_local_hdr_edit',
    'feature_is_support_uhdr_edit',
    'feature_is_support_ai_deblur',
    'feature_is_support_ai_dereflection',
    'feature_is_support_ai_eliminate',
    'feature_is_support_eliminate_pen',
    'feature_is_support_ai_composition',
    'feature_is_support_ai_lighting',
    'feature_is_support_ai_face_hd',
    'feature_is_support_ai_id_photo',
    'feature_is_support_ai_best_take',
    'feature_is_support_ai_matting',
    'feature_is_support_ai_deglare',
    'feature_is_support_plugin_available',
    'feature_is_support_show_ai_logo',
    'feature_is_support_deblur_recommend',
    'feature_is_support_dereflection_recommend',
    'feature_is_support_ai_best_take_recommend',
    'feature_is_support_ai_lighting_recommend',
    # Not a feature_is_support_* entry: AIUnitPrivacyInterceptor resolves this
    # through the same ConfigAbility lookup, and off OOS it defaults false. Every
    # AI apply then fails with error 10109 the moment it runs, even though the
    # tool is visible and AIUnit is healthy. Forcing it here is what the
    # hand-patched, pm-installed Gallery was doing on the test device; this puts
    # the same fix in the build so it survives a flash.
    'is_agree_ai_unit_privacy',
)

# Deliberately NOT forced: feature_is_support_ai_defog. Defog reaches the ODM
# APS/libAlgoProcess path, which segfaults in doIPUArcDeHazyProcess -- showing
# the entry just hands the user a crash.
#
# Forced for Perfect Shot, not for HDR's own sake: local_hdr_edit + uhdr_edit.
#
# Perfect Shot builds its face-picker thumbnails by rendering each candidate
# into the editor preview surface and screenshotting it. The capture reads the
# SurfaceView, so it only sees pixels if the GPU path drew there. Off OOS the
# whole HDR display pipeline is dark and the editor falls back to CPU frames,
# leaving that surface empty -- one failed capture per candidate:
#
#   AIGallery_AIBestTakeSection: takeScreenShot: SurfaceView fetch Bitmap failed
#
# Measured over paired Perfect Shot runs, stock vs ours:
#
#   HdrTransitionScene      71  vs  0
#   UhdrRenderer           249  vs  0
#   Editor#ProxyGpuFrame     2  vs  0
#   Editor#ProxyCpuFrame     2  vs 65
#
# The gate is HdrEditUtils.m() (com/oplus/aiunit/vision/t8b), reached from both
# EditablePhotoPage and HdrImageScene:
#
#   if (feature_is_support_local_hdr_edit && d2e.o(media)) return true;
#   if (feature_is_support_uhdr_edit      && d2e.w(media)) return true;
#   return false;                     -> "[...] not support hdr edit"
#
# Both resolve false off OOS, so it always returns false. Note each flag is
# ALSO gated on the media itself (d2e.o / d2e.w), so forcing them cannot push an
# SDR image down the HDR path -- it only stops us claiming a CPH2653 cannot do
# something it demonstrably does on stock.
#
# Evidence-based but NOT flash-verified: the causal chain from these flags to
# the empty surface is inferred from the counts above plus the decompiled gate,
# not observed end to end. If Perfect Shot still shows no candidates, re-check
# whether ProxyGpuFrame/UhdrRenderer appear at all before touching anything else
# -- if they are still 0, the gate is somewhere further upstream.

# Deliberately NOT forced: feature_is_support_ipu_beauty. Same shape of bug as
# rm_ai_deblur below -- it selects a backend rather than enabling anything, and
# forcing it is what BROKE Retouch. MenuVM gates the model loader on it:
#
#   const-string v5, "feature_is_support_ipu_beauty"
#   invoke-static {v1, v5, v4}, e26->f(ILjava/lang/String;Z)Z
#   move-result v1
#   if-nez v1, :cond_6b            <- flag TRUE: jump PAST the loader
#   new-instance v4, Lcom/oplus/aiunit/vision/ti3;   (BeautyModelLoader)
#
# True means "this device does beauty on the IPU", so Gallery never builds the
# loader and never fetches the downloadable ArcSoft model. On stock the flag is
# false and BeautyModelLoader pulls the component down:
#
#   BeautyModelLoader: RemoteModelInfoManager.fetch onSuccess.
#     RemoteModelInfo(name=BeautySource, version=2, zipMd5=38fb...)
#
# On our build that tag logs NOTHING -- the fetch was not failing, it was never
# invoked. Note the download runs through RemoteModelInfoManager, NOT
# ComponentDownloadManager, which is why greps for the latter found nothing.
#
# feature_is_support_beauty_entrance is a different flag and stays forced -- it
# is what shows the Retouch entry, and it lives in a separate class.

# Deliberately NOT forced: feature_is_support_rm_ai_deblur. Forcing it is what
# BROKE AI Unblur -- this flag does not enable anything, it switches which
# backend the tool uses. AIRepairIntroductionConfig picks the command from it:
#
#   if-nez v0, :cond_28              # v0 = feature_is_support_rm_ai_deblur
#       const-string v0, "cmd_deblur"    <- false: cloud, cloud_image_deblur
#       goto :goto_2a
#   :cond_28
#       const-string v0, "cmd_sharpen"   <- true:  local, vision_image_sharpen
#
# cmd_sharpen routes through RMDeblurClient.sharpenImageLocally() and needs OAP
# vision_image_sharpen (1052679) plus OAA 17833993. Neither is in our packs, in
# either /data backup, or on stock -- so on device it died as:
#
#   UnitConfig(vision_image_sharpen, 1052679, ...) not support
#   local file DependConfig(id=1052679, strict=true), invalid, version: -1
#   queryDetectInfo: state=13 checkErrorCode=kErrorRouteDisabled
#   AIUnit-SDK(gallery)-ImageSharpenClient: runAction no started!
#
# and surfaced as "errorInfo=(-1, result is null)". Left false, the tool takes
# cmd_deblur to cloud_image_deblur, which we ship and which reports state=3
# kErrorNone -- the same unit a stock capture ran at errCode=0. Stock does not
# set this flag either.
#
# Deliberately NOT forced: feature_is_support_ai_graffiti (AI Sketch). Removed
# 2026-08-04 after exhausting every source. AI Sketch needs AIUnit unit
# `cloud_image_ai_graffiti`, which is absent from unit_config_list.json, from
# this device, from both /data backups, from the 64 cached server configs --
# and, confirmed by a stock ColorOS capture the same day, from stock itself.
# Stock ships 13 plugin packs and graffiti is not among them, so there is no
# device or firmware we can reach that has the pack. Forcing the flag only
# rendered a button whose every tap ends in "unit config not found". The
# Gallery-side implementation is fully present (~200 classes under
# com.oplus.tbluniformeditor.plugins.aigraffiti), so restoring this line is all
# that is needed if a pack ever surfaces.

# Downloadable Gallery components, keyed by the config entry that gates them.
#
# These are NOT AIUnit packs and none of the unit_config_list/Orange.json
# machinery applies -- they come down through Gallery's own
# ComponentDownloadManager into files/component/<Name>/. ModelConfig
# (com/oplus/aiunit/vision/oje) resolves availability as o() = n() && m():
# n() validates the component dir against its config.json, m() checks each
# required file is present, and e() supplies the wanted version by reading
# these keys out of GalleryCommonListConfig.
#
# The default asset ships face/label versions but has no beauty entry at all,
# so e() falls through to its -1 default and the download is never even
# attempted. That is the whole reason Retouch is dead off OOS: it is not
# blocked, it is never asked for.
#
#   Retouch -> BeautySource -> libarcsoft_beauty_ex.so (20 MB),
#              liboplus_image_process.so, libmpbase.so
#
# Version numbers are the cloud-config download version, NOT the component's
# internal config.json mVersion -- verified on a stock capture where
# FaceModelSource carried mVersion=1 while face_component_version was 16. The
# values below are the ones a stock CPH2653 actually had installed.
GALLERY_COMPONENT_VERSIONS = {
    'beauty_component_version': 2,
    'face_component_version': 16,
    'label_component_version': 17,
    'video_label_component_version': 220,
}

GALLERY_COMMON_CONFIG_ASSET = 'assets/default_gallery_common_list_config.xml'


def blob_fixup_gallery_component_versions(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    # Ask for the components Gallery would otherwise never request. Editing the
    # bundled default rather than patching smali keeps this honest: a live cloud
    # config still wins, because GalleryCommonListConfig only falls back to this
    # asset when the server has not answered. So this raises the floor without
    # pinning anyone to a stale version.
    if tmp_dir is None:
        return

    config = Path(tmp_dir) / GALLERY_COMMON_CONFIG_ASSET
    if not config.exists():
        return

    data = config.read_text(encoding='utf-8')
    original = data

    for key, version in GALLERY_COMPONENT_VERSIONS.items():
        entry = f'<{key}>{version}</{key}>'
        existing = re.search(rf'<{key}>\s*(\d+)\s*</{key}>', data)
        if existing is None:
            # No entry at all (beauty). Put it beside the other component
            # versions rather than at the end of the file -- <filter-conf> is
            # order-insensitive, but keeping them together is what makes the
            # missing one obvious next time.
            anchor = re.search(r'([ \t]*)<face_component_version>[^\n]*\n', data)
            if anchor is None:
                continue
            data = data.replace(
                anchor.group(0), f'{anchor.group(0)}{anchor.group(1)}{entry}\n', 1
            )
        elif int(existing.group(1)) < version:
            data = data.replace(existing.group(0), entry, 1)

    if data != original:
        config.write_text(data, encoding='utf-8')


GALLERY_OLIVE_ANCHOR = '    :goto_olive_check_done\n'


def blob_fixup_gallery_force_ai_flags(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    # Gallery hides its AI tools behind ConfigAbilityWrapper feature flags,
    # resolved through the ColorOS AppFeature config provider. Off OOS that
    # provider does not exist, every feature_is_support_* lookup returns false
    # and the editor entries never appear -- which is why the AI menu is empty
    # even with AIUnit healthy and its packs installed.
    #
    # Same trick 0005 uses for Live Photo, extended to the rest of the suite.
    if tmp_dir is None:
        return

    # The class name is obfuscated and moves between blobs (c25 -> e26 so far),
    # so find the file by the anchor 0005 leaves behind rather than by name.
    root = Path(tmp_dir)
    smali = None
    for candidate in sorted(root.glob('smali_classes*/com/oplus/**/*.smali')):
        if GALLERY_OLIVE_ANCHOR in candidate.read_text(encoding='utf-8'):
            smali = candidate
            break
    if smali is None:
        return

    data = smali.read_text(encoding='utf-8')
    if 'cond_force_ai_true' in data:
        return

    chain = ''
    for flag in GALLERY_AI_FEATURE_FLAGS:
        chain += (
            f'    const-string v0, "{flag}"\n'
            '\n'
            '    invoke-virtual {v0, p0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z\n'
            '\n'
            '    move-result v1\n'
            '\n'
            '    if-nez v1, :cond_force_ai_true\n'
            '\n'
        )

    # Reuses v0/v1 exactly as 0005 does, so the method's .locals still covers it.
    inject = (
        chain
        + '    goto :goto_force_ai_done\n'
        '\n'
        '    :cond_force_ai_true\n'
        '    const/4 v0, 0x1\n'
        '\n'
        '    return v0\n'
        '\n'
        '    :goto_force_ai_done\n'
        '\n'
    )

    smali.write_text(
        data.replace(GALLERY_OLIVE_ANCHOR, GALLERY_OLIVE_ANCHOR + '\n' + inject, 1),
        encoding='utf-8',
    )


# Gallery builds every cloud request URL from a base it reads out of the ColorOS
# AppFeature provider:
#
#   FeatureUtils$e.g <- AppFeatureProviderUtils.c(cr, "com.oplus.gallery3d.videoeditor_url")
#
# which SecurityUrlImpl returns and OplusNetServiceManager concatenates with the
# request path. Off OOS that provider does not exist -- the same reason the
# feature flags above all read false -- so the base comes back empty and every
# request is issued against a bare path:
#
#   NetworkExecutor: doTask, failed! error=Expected URL scheme 'http' or 'https'
#     but no colon was found
#   RemoteModelInfoManager: fetch, failed! had init but cache error
#
# GetModelRequest is on this path, so with no base URL the AI models can never be
# fetched and the tools that need them stay broken no matter what AIUnit does.
#
# The host below is the one AlphaDroid hardcodes (db752670). Despite the "-cn" in
# the name it is not a mainland-China server: it resolves into AWS ap-southeast-1
# (52.220.204.101 / 18.136.53.85) and answers with a valid certificate, i.e. it is
# the export endpoint. Checked because this ships to NA/EU/IN units alike -- there
# is no regional variant to pick instead, -sg/-in/-eu/-us/-row all fail to resolve.
GALLERY_MODEL_ENDPOINT = 'https://fourier-videoclip-cn.allawntech.com'

# Deliberately NOT touched: the sibling base URL, FeatureUtils$e.i from
# "com.oplus.gallery3d.rm_editor_url". "rm" is Realme, not "remove" -- its only
# consumers are TemplateResourceRequest/Manager and
# RealmeRestrictWatermarkMetadataRequest, none of which are on the AI model path.
# Its real value is not in the dump (these keys are cloud-pushed, not shipped in
# my_product/etc/extension), so there is nothing to set it to but a guess.


def blob_fixup_gallery_model_endpoint(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    # Both classes are obfuscated and the names move between blobs -- upstream's
    # SecurityUrlImpl is "eli", ours is "bck" -- so match on the .source name,
    # which survives. Note smali*/ and not smali_classes*/: SecurityUrlImpl lands
    # in classes.dex, which apktool unpacks to a plain smali/.
    root = Path(tmp_dir)
    security_url = None
    net_services = []
    for candidate in sorted(root.glob('smali*/com/oplus/**/*.smali')):
        text = candidate.read_text(encoding='utf-8', errors='ignore')
        if '.source "SecurityUrlImpl.java"' in text:
            security_url = (candidate, text)
        elif '.source "OplusNetServiceManager.java"' in text:
            net_services.append((candidate, text))

    if security_url is None:
        return

    path, data = security_url
    if GALLERY_MODEL_ENDPOINT in data:
        return

    match = re.search(r'^\.class[^\n]* (L[\w/$]+;)$', data, re.M)
    if match is None:
        return
    class_desc = match.group(1)

    # R8 merges unrelated statics into this class, so anchor on the one virtual
    # method that returns a String rather than replacing the class wholesale.
    match = re.search(
        r'^\.method (public (?:final )?(\w+)\(\)Ljava/lang/String;)$', data, re.M
    )
    if match is None:
        return
    getter = f'{class_desc}->{match.group(2)}('

    fixed = _replace_smali_method(
        data,
        match.group(1),
        '    .registers 2\n'
        '\n'
        f'    const-string v0, "{GALLERY_MODEL_ENDPOINT}"\n'
        '\n'
        '    return-object v0\n',
    )
    if fixed != data:
        path.write_text(fixed, encoding='utf-8')

    # The callers null-check the SecurityUrlImpl instance and fall back to "",
    # which concatenates to a bare path just the same, so pin them too.
    #
    # Selecting on a call to the getter, not merely a mention of the class: the
    # sibling builder that reads the Realme base URL inline still names the class
    # in IAppDM.a()'s return type, and matching on the descriptor alone rewrote
    # that one too.
    body = (
        '    .registers 4\n'
        '\n'
        '    invoke-static {p0}, Landroid/text/TextUtils;->isEmpty(Ljava/lang/CharSequence;)Z\n'
        '\n'
        '    move-result v0\n'
        '\n'
        '    if-eqz v0, :cond_endpoint_build\n'
        '\n'
        '    const/4 p0, 0x0\n'
        '\n'
        '    return-object p0\n'
        '\n'
        '    :cond_endpoint_build\n'
        '    new-instance v0, Ljava/lang/StringBuilder;\n'
        '\n'
        '    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V\n'
        '\n'
        f'    const-string v1, "{GALLERY_MODEL_ENDPOINT}"\n'
        '\n'
        '    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
        '\n'
        '    invoke-virtual {v0, p0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
        '\n'
        '    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
        '\n'
        '    move-result-object p0\n'
        '\n'
        '    return-object p0\n'
    )

    for path, data in net_services:
        fixed = data
        for match in re.finditer(
            r'^\.method (public static \w+\(Ljava/lang/String;\)Ljava/lang/String;)$',
            data,
            re.M,
        ):
            signature = match.group(1)
            current = re.search(
                rf'(?ms)^\.method {re.escape(signature)}\n(.*?)^\.end method', data
            )
            if current is None or getter not in current.group(1):
                continue
            fixed = _replace_smali_method(fixed, signature, body)
        if fixed != data:
            path.write_text(fixed, encoding='utf-8')


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


def blob_fixup_aon_disable_ezpay_settings(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    """Keep AON camera AI; strip EZ Pay Settings injection (Intelligent Perception)."""
    if tmp_dir is None:
        return
    try:
        import pyaxml
    except ImportError:
        return

    candidates = [
        Path(tmp_dir) / 'AndroidManifest.xml',
        Path(tmp_dir) / 'original' / 'AndroidManifest.xml',
    ]
    target = None
    for c in candidates:
        if c.exists() and c.stat().st_size > 0:
            head = c.read_bytes()[:4]
            if head[:2] == b'\x03\x00' or head == b'\x03\x00\x08\x00' or head[0] != ord('<'):
                target = c
                break
    if target is None:
        manifest = Path(tmp_dir) / 'AndroidManifest.xml'
        if manifest.exists() and manifest.read_text(encoding='utf-8', errors='ignore').lstrip().startswith('<'):
            data = manifest.read_text(encoding='utf-8')
            # Drop Settings injection action; keep AON runtime.
            data = data.replace(
                '<action android:name="com.android.settings.MANUFACTURER_APPLICATION_SETTING"/>',
                '',
            )
            data = re.sub(
                r'<provider\b[^>]*IntelligentSearchIndexablesProvider[\s\S]*?</provider>',
                '',
                data,
                count=1,
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
        name = get_a(prov, 'name') or ''
        if 'IntelligentSearchIndexablesProvider' in name:
            app.remove(prov)
    for act in [e for e in app if e.tag.split('}')[-1] == 'activity']:
        name = get_a(act, 'name') or ''
        if 'IntelligentPerceptionActivity' not in name:
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
    # apktool_patch() expanded so the AI feature flags can be forced after the
    # patches land but before the APK is packed back up.
    'system_ext/priv-app/OppoGallery2/OppoGallery2.apk': blob_fixup()
        .apktool_unpack('patches-gallery')
        .patch_dir('patches-gallery')
        .call(blob_fixup_gallery_force_ai_flags)
        .call(blob_fixup_gallery_model_endpoint)
        .call(blob_fixup_gallery_component_versions)
        .apktool_pack()
        .stripzip(),
    'system_ext/priv-app/AIUnit/AIUnit.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_src)
        .call(blob_fixup_aiunit_disable_settings)
        .call(blob_fixup_aiunit_baseos_empty)
        .call(blob_fixup_aiunit_authorize_camera)
        .call(blob_fixup_aiunit_plugin_so_permissions)
        .call(blob_fixup_aiunit_preinstall_packs)
        .apktool_pack()
        .stripzip(),
    'system_ext/priv-app/AONService/AONService.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_src)
        .call(blob_fixup_aon_disable_ezpay_settings)
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

# apktool needs a lot of scratch space for this module: OppoGallery2 is ~300 MB
# with 31 dex directories, and decoding plus repacking it needs well over 10 GB
# at once. /tmp is a tmpfs on the usual build hosts and is nowhere near that.
#
# Worth being explicit about, because the failure is badly disguised. When the
# scratch filesystem fills, aapt2 does not report ENOSPC -- it reports
#
#     error: failed to write entry data
#     <file>.json: error: file failed to compile
#
# which reads like a corrupt resource in the APK and sends you looking at the
# wrong thing entirely. Worse, extract-utils empties its output tree before it
# repopulates, so a crash partway through leaves the blob repo stripped of
# Android.bp, camera-vendor.mk and a couple of hundred blobs. That is recoverable
# with `git checkout -- .` in vendor/oplus/camera/camera, but only if you know
# that is what happened.
REQUIRED_SCRATCH_BYTES = 24 * 1024**3


def use_scratch_dir_with_space():
    """
    Point tempfile at a filesystem with room for the apktool work dirs.

    Decided purely on free space, including when TMPDIR is already set. An
    explicit TMPDIR that is too small is not a preference worth honouring -- it
    just reproduces the failure this exists to avoid -- so it is reported and
    overridden rather than obeyed.
    """
    # gettempdir() already resolves TMPDIR/TEMP/TMP, so this covers both the
    # inherited-environment and the plain /tmp case.
    default_tmp = tempfile.gettempdir()
    if shutil.disk_usage(default_tmp).free >= REQUIRED_SCRATCH_BYTES:
        return

    scratch = os.path.join(
        os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'),
        'extract-utils',
        'scratch',
    )
    os.makedirs(scratch, exist_ok=True)

    os.environ['TMPDIR'] = scratch
    tempfile.tempdir = scratch

    # Java resolves java.io.tmpdir at startup and ignores TMPDIR, so apktool and
    # the aapt2 it spawns would still land back in /tmp without this. Appended
    # rather than assigned so an existing JAVA_TOOL_OPTIONS (heap size, GC) is
    # kept; the last -D on the line wins.
    java_options = os.environ.get('JAVA_TOOL_OPTIONS', '')
    os.environ['JAVA_TOOL_OPTIONS'] = (
        f'{java_options} -Djava.io.tmpdir={scratch}'.strip()
    )

    free_gib = shutil.disk_usage(scratch).free / 1024**3
    print(
        f'{default_tmp} is too small for apktool, using {scratch} '
        f'({free_gib:.0f} GiB free)'
    )
    if shutil.disk_usage(scratch).free < REQUIRED_SCRATCH_BYTES:
        print(
            f'warning: {scratch} has under '
            f'{REQUIRED_SCRATCH_BYTES / 1024**3:.0f} GiB free either; the '
            f'OppoGallery2 repack may still fail. Set TMPDIR to somewhere '
            f'with more room.'
        )


if __name__ == '__main__':
    use_scratch_dir_with_space()

    utils = ExtractUtils.device(module)
    utils.run()
