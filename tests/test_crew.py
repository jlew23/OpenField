"""Crew swap tests: chunk planning, people tracking through contact, the VACE workflow file, and a full run."""
import json, math, tempfile, unittest, unittest.mock
from pathlib import Path
from fractions import Fraction

import numpy as np
from PIL import Image, ImageDraw

import comfy_bridge
import crew_swap

ROOT = Path(__file__).resolve().parents[1]


def _clip(folder, n=48, w=96, h=160, bump=None):
    """Two coloured 'people' (green left, blue right) that optionally touch around frame `bump`."""
    import av
    (folder / 'clean-masks').mkdir(parents=True)
    outs = {}
    for name in ('original', 'depth', 'mask', 'composite-silent'):
        c = av.open(str(folder / f'{name}.mp4'), 'w')
        s = c.add_stream('libx264', rate=24)
        s.width, s.height, s.pix_fmt, s.options = w, h, 'yuv420p', {'crf': '10'}
        outs[name] = (c, s)
    for i in range(n):
        gap = 26 if bump is None else 26 - 16 * math.exp(-((i - bump) / 4) ** 2)
        img = Image.new('RGB', (w, h), (150, 110, 60))
        m = Image.new('L', (w, h), 0)
        d, dm = ImageDraw.Draw(img), ImageDraw.Draw(m)
        for cx, col in ((w / 2 - gap, (40, 170, 70)), (w / 2 + gap, (60, 80, 210))):
            d.rectangle([cx - 12, 40, cx + 12, 140], fill=col)
            dm.rectangle([cx - 12, 40, cx + 12, 140], fill=255)
        m.save(folder / 'clean-masks' / f'mask_{i:04d}.png')
        rgb, mk = np.asarray(img), np.asarray(m)
        dep = np.repeat(np.where(mk > 0, 200, 30).astype(np.uint8)[..., None], 3, 2)
        for name, a in (('original', rgb), ('depth', dep), ('mask', np.repeat(mk[..., None], 3, 2)),
                        ('composite-silent', np.where(mk[..., None] > 0, dep, rgb))):
            c, s = outs[name]
            f = av.VideoFrame.from_ndarray(np.ascontiguousarray(a), format='rgb24')
            f.pts = i
            for p in s.encode(f):
                c.mux(p)
    for c, s in outs.values():
        for p in s.encode():
            c.mux(p)
        c.close()


class Planning(unittest.TestCase):
    def test_chunks_cover_with_overlap(self):
        self.assertEqual(crew_swap.plan_chunks(50), [(0, 50)])
        chunks = crew_swap.plan_chunks(288)  # 18 s at 16 fps
        self.assertEqual(chunks[0], (0, 81))
        self.assertEqual(chunks[-1][1], 288)
        for (a0, b0), (a1, b1) in zip(chunks, chunks[1:]):
            self.assertEqual(a1, b0 - crew_swap.OVERLAP)
        self.assertTrue(all(b - a <= crew_swap.CHUNK for a, b in chunks))

    def test_wan_lengths_and_size(self):
        self.assertEqual([crew_swap.wan_length(n) for n in (1, 5, 6, 29, 81)], [1, 5, 9, 29, 81])
        self.assertEqual(crew_swap.gen_size(540, 960), (464, 832))
        self.assertEqual(crew_swap.gen_size(1920, 1080), (832, 464))


class People(unittest.TestCase):
    def test_two_people_stay_apart_while_touching(self):
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t)
            _clip(folder, bump=24)
            info = crew_swap.split_people(folder, status=lambda s: None)
            self.assertEqual(info['count'], 2)
            self.assertGreater(info['merged_frames'], 0)
            self.assertTrue((folder / 'people' / 'person-1.jpg').exists())
            import av
            with av.open(str(folder / 'original.mp4')) as c:
                frames = [f.to_ndarray(format='rgb24') for f in c.decode(video=0)]
            for i in (18, 22, 24, 26, 30):
                lab = np.asarray(Image.open(folder / 'people' / f'label_{i:04d}.png'))
                o = frames[i].astype(int)
                green = (o[..., 1] > 130) & (o[..., 0] < 90)
                blue = (o[..., 2] > 170) & (o[..., 0] < 100)
                self.assertGreater((lab[green] == 1).mean(), 0.95, f'frame {i}')
                self.assertGreater((lab[blue] == 2).mean(), 0.95, f'frame {i}')

    def test_person_mask_never_reaches_the_other_person(self):
        lab = np.zeros((40, 40), np.uint8)
        lab[10:30, 5:19] = 1
        lab[10:30, 19:35] = 2
        m = crew_swap._person_masks([lab], 1, 4)[0]
        self.assertFalse((m & (lab == 2)).any())
        self.assertTrue(m[10:30, 1:5].any())  # grew outward on the free side


class Workflow(unittest.TestCase):
    def test_shipped_vace_workflow_is_tagged(self):
        wf = json.loads((ROOT / 'workflows' / 'wan21-vace-swap.json').read_text())
        self.assertTrue(comfy_bridge._is_api_format(wf))
        self.assertTrue(comfy_bridge.is_vace(wf))
        roles = comfy_bridge.locate(wf)
        for role in ('OF_REFERENCE', 'OF_CONTROL', 'OF_MASK', 'OF_PROMPT', 'OF_NEGATIVE', 'OF_SEED', 'OF_FRAMES'):
            self.assertIn(role, roles)
        self.assertNotIn('OF_VIDEO', roles)
        self.assertEqual(comfy_bridge._size_node(wf, roles), roles['OF_FRAMES'])
        classes = {n['class_type'] for n in wf.values()}
        self.assertTrue({'WanVaceToVideo', 'TrimVideoLatent', 'LoadVideo', 'SaveImage'} <= classes)


class Run(unittest.TestCase):
    def test_crew_run_with_fake_engine(self):
        import av
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t)
            _clip(folder, n=96)  # 4 s
            Image.new('RGB', (32, 48), (230, 30, 30)).save(folder / 'a.png')
            Image.new('RGB', (32, 48), (240, 220, 20)).save(folder / 'b.png')
            from mask_review import review, fingerprint
            with self.assertRaises(ValueError):
                crew_swap.run(folder, {1: folder / 'a.png'}, status=lambda s: None)
            review(folder, True, 'test', fingerprint(folder))
            calls = []

            def queue(workflow, files, prompt, seed, frames=None, size=None):
                calls.append({'files': {k: Path(v).name for k, v in files.items()}, 'frames': frames, 'size': size, 'seed': seed})
                ref = np.asarray(Image.open(files['OF_REFERENCE']).convert('RGB')).reshape(-1, 3).mean(0)
                with av.open(str(files['OF_CONTROL'])) as c:
                    ctrl = [f.to_ndarray(format='rgb24') for f in c.decode(video=0)]
                with av.open(str(files['OF_MASK'])) as c:
                    msk = [f.to_ndarray(format='rgb24')[..., :1] > 127 for f in c.decode(video=0)]
                return [np.where(m, ref, x).astype(np.uint8) for x, m in zip(ctrl, msk)]

            out = crew_swap.run(folder, {1: folder / 'a.png', 2: folder / 'b.png'}, seed=5, start=0.5, seconds=3,
                                status=lambda s: None, queue=queue, fetch=lambda job, status, label: job)
            self.assertEqual(out.name, 'crew-final.mp4')
            self.assertEqual(len(calls), 2)  # 3 s fits in one chunk per person
            self.assertEqual(calls[0]['frames'], 49)
            self.assertEqual(calls[0]['size'], crew_swap.gen_size(96, 160))
            with av.open(str(out)) as c:
                frames = [f.to_ndarray(format='rgb24') for f in c.decode(video=0)]
            self.assertEqual(len(frames), 72)
            mid = frames[36].astype(int)
            self.assertGreater(mid[90, 22, 0], 180)  # person 1 now red
            self.assertLess(mid[90, 22, 1], 90)
            self.assertGreater(mid[90, 74, 1], 160)  # person 2 now yellow
            self.assertLess(abs(mid[5, 48] - np.array([150, 110, 60])).max(), 12)  # background untouched
            # finished chunks are reused on a second run
            calls.clear()
            crew_swap.run(folder, {1: folder / 'a.png', 2: folder / 'b.png'}, seed=5, start=0.5, seconds=3,
                          status=lambda s: None, queue=queue, fetch=lambda job, status, label: job)
            self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()


class ExistingModels(unittest.TestCase):
    def _wf(self):
        return json.loads((ROOT / 'workflows' / 'wan21-vace-swap.json').read_text())

    def _run(self, unet, gguf=(), clip=('umt5_xxl_fp16.safetensors',), vae=('wan_2.1_vae.safetensors', 'wan_alpha_2.1_vae_alpha_channel.safetensors')):
        table = {('UNETLoader', 'unet_name'): list(unet), ('UnetLoaderGGUF', 'unet_name'): list(gguf),
                 ('CLIPLoader', 'clip_name'): list(clip), ('VAELoader', 'vae_name'): list(vae)}
        wf = self._wf()
        with unittest.mock.patch.object(comfy_bridge, '_options', lambda c, f: table.get((c, f), [])):
            swaps = comfy_bridge.resolve_models(wf)
        return wf, swaps

    def test_uses_files_already_on_disk(self):
        wf, swaps = self._run(['Wan2.1\\wan2.1_vace_14B_fp8_e4m3fn.safetensors', 'wan2.1_i2v_480p_14B.safetensors'])
        self.assertEqual(wf['1']['inputs']['unet_name'], 'Wan2.1\\wan2.1_vace_14B_fp8_e4m3fn.safetensors')
        self.assertEqual(wf['2']['inputs']['clip_name'], 'umt5_xxl_fp16.safetensors')
        self.assertEqual(wf['3']['inputs']['vae_name'], 'wan_2.1_vae.safetensors')
        self.assertEqual(len(swaps), 2)

    def test_exact_match_left_alone(self):
        wf, swaps = self._run(['wan2.1_vace_1.3B_fp16.safetensors'], clip=['umt5_xxl_fp8_e4m3fn_scaled.safetensors'])
        self.assertEqual(swaps, [])

    def test_gguf_build(self):
        wf, swaps = self._run([], gguf=['Wan2.1-VACE-14B-Q4_K_M.gguf'])
        self.assertEqual(wf['1']['class_type'], 'UnetLoaderGGUF')
        self.assertEqual(wf['1']['inputs'], {'unet_name': 'Wan2.1-VACE-14B-Q4_K_M.gguf'})

    def test_missing_vace_says_so(self):
        with self.assertRaises(ValueError) as e:
            self._run(['wan2.1_i2v_480p_14B.safetensors'])
        self.assertIn('VACE', str(e.exception))
