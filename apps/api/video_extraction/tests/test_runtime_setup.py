"""Launcher integration, mocked installation/model loads; no network or API."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from video_extraction.pipeline import runtime_setup as m, connected
from video_extraction.shared.common import read,save
from video_extraction._layout import PROJECT_ROOT


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.p={'tasks':[{'kind':'audio'}],'source_plan':{'config':{'language':'ko'}},
                'tool_runtime':{'alignment_python':str(self.root/'env/bin/python'),'alignment_model':None}}

    def test_audio_setup_before_ready_and_report(self):
        with patch.object(connected,'verify',return_value=self.p),patch.object(m.rt,'audit',return_value={'checks':[]}),patch.object(m,'ensure_alignment',return_value={'model_cache_ready':True}) as ensure:
            r=m.prepare_common(self.root)
        ensure.assert_called_once_with(self.p['tool_runtime']['alignment_python'],'ko',None)
        self.assertEqual(r['state'],'ready');self.assertEqual(r['api_calls'],0)

    def test_code_pdf_ppt_image_without_audio_do_not_install_whisperx(self):
        for kind in ('code','visual','video_coverage'):
            p={**self.p,'tasks':[{'kind':kind}]}
            with patch.object(connected,'verify',return_value=p),patch.object(m.rt,'audit',return_value={'checks':[]}),patch.object(m,'ensure_alignment',side_effect=AssertionError('unexpected setup')):
                self.assertEqual(m.prepare_common(self.root)['alignment']['state'],'not_required')

    def test_setup_failure_is_recorded_and_propagated(self):
        with patch.object(connected,'verify',return_value=self.p),patch.object(m.rt,'audit',return_value={'checks':[]}),patch.object(m,'ensure_alignment',side_effect=RuntimeError('install failed')):
            with self.assertRaises(RuntimeError):m.prepare_common(self.root)
        self.assertEqual(read(self.root/'tool-setup.json')['state'],'blocked_before_api')

    def test_stale_plan_or_missing_core_tools_stops_before_installation(self):
        with patch.object(connected,'verify',side_effect=ValueError('stale')),patch.object(m,'ensure_alignment') as ensure:
            with self.assertRaises(ValueError):m.prepare_common(self.root)
            ensure.assert_not_called()
        with patch.object(connected,'verify',return_value=self.p),patch.object(m.rt,'audit',return_value={'checks':[{'tool':'ffmpeg','required':True,'ok':False}]}),patch.object(m,'ensure_alignment') as ensure:
            with self.assertRaises(ValueError):m.prepare_common(self.root)
            ensure.assert_not_called()

    def test_installed_and_cached_does_not_pip_install_or_download(self):
        with patch.object(m.rt,'imports',return_value={'ok':True}),patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as run:
            r=m.ensure_alignment(sys.executable,'ko')
        self.assertEqual(run.call_count,1);self.assertEqual(run.call_args.args[0][-1],'offline')
        self.assertFalse(r['installed']);self.assertFalse(r['download_attempted'])

    def test_missing_environment_installs_then_verifies_offline_model_cache(self):
        calls=[]
        def run(args,**kwargs):
            calls.append(args)
            # First offline probe fails; subsequent download+offline recheck succeeds.
            return subprocess.CompletedProcess(args,1 if args[-1]=='offline' and sum(c[-1]=='offline' for c in calls)==1 else 0)
        with patch.object(m.rt,'imports',side_effect=[{'ok':False},{'ok':True}]),patch.object(m.subprocess,'run',side_effect=run):
            r=m.ensure_alignment(self.root/'env/bin/python','ko')
        self.assertTrue(r['installed']);self.assertTrue(r['download_attempted'])
        self.assertEqual(calls[0][1:3],['-m','venv'])
        self.assertEqual([a[-1] for a in calls if a[1]=='-c' and a[2]==m.WARMUP],['offline','download','offline'])

    def test_failed_install_import_does_not_try_to_load_model(self):
        with patch.object(m.rt,'imports',return_value={'ok':False}),patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as run:
            with self.assertRaisesRegex(ValueError,'import_check_failed'):m.ensure_alignment(self.root/'env/bin/python','ko')
        self.assertFalse(any(m.WARMUP in c.args[0] for c in run.call_args_list))

    def test_launcher_stops_before_key_access_when_setup_fails(self):
        launcher=self.root/'공통데이터_처리.command'
        launcher.write_text((PROJECT_ROOT/'공통데이터_처리.command').read_text())
        (self.root/'공통도구_준비후_처리.command').write_text('#!/bin/zsh\nprint setup_attempt > setup-attempt.txt\nexit 19\n')
        p=subprocess.run(['zsh',str(launcher),'run','--output','any'],input='',capture_output=True,text=True,
                         env={'PATH':'/usr/bin:/bin','DATA_PIPELINE_PYTHON':sys.executable})
        self.assertNotEqual(p.returncode,0);self.assertTrue((self.root/'setup-attempt.txt').exists())
        self.assertNotIn('Gemini API 키',p.stdout+p.stderr)

    def test_local_only_launcher_never_runs_setup(self):
        launcher=self.root/'공통데이터_처리.command';launcher.write_text((PROJECT_ROOT/'공통데이터_처리.command').read_text())
        (self.root/'공통도구_준비후_처리.command').write_text('#!/bin/zsh\nprint BAD > setup-attempt.txt\nexit 19\n')
        package=self.root/'video_extraction/pipeline';package.mkdir(parents=True)
        (self.root/'video_extraction/__init__.py').touch();(package/'__init__.py').touch()
        (package/'connected.py').write_text('print("OFFLINE_HANDLER")\n')
        p=subprocess.run(['zsh',str(launcher),'run','--output','any','--local-only'],capture_output=True,text=True,
                         env={'PATH':'/usr/bin:/bin','DATA_PIPELINE_PYTHON':sys.executable})
        self.assertEqual(p.returncode,0,p.stderr);self.assertIn('OFFLINE_HANDLER',p.stdout)
        self.assertFalse((self.root/'setup-attempt.txt').exists())

    def test_legacy_setup_entrypoint_delegates_once(self):
        setup=self.root/'공통도구_준비후_처리.command';setup.write_text((PROJECT_ROOT/'공통도구_준비후_처리.command').read_text())
        (self.root/'공통데이터_처리.command').write_text('#!/bin/zsh\nprint -l -- "$@" > forwarded.txt\n')
        p=subprocess.run(['zsh',str(setup),'sample-output'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        text=(self.root/'forwarded.txt').read_text();self.assertIn('sample-output',text);self.assertIn('run',text)


if __name__=='__main__':unittest.main()
