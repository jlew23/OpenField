"""Station tests: flow engine, beat analysis, Bible parsing, grading, game layer, Forge, LLM settings, actions, ComfyUI bridge."""
import json, tempfile, unittest, wave
from pathlib import Path
from unittest.mock import patch, Mock

import numpy as np

from station import db, flow, lyrics, beat, bible, grading, academy, forge, llm, jarvis, personas
import comfy_bridge

VERSE = """## Verse 1
**DON:** *(low and slow)*
Neon on the river, I can see the city shiver
Paper in the glovebox, never trust a giver
**DEMON:**
Lightning in a bottle and I'm rattling the throttle
Ripping out the model, I'm a riot with a bottle
"""

MINI_BIBLE = """# THE RAP WRITING BIBLE

# THE SKILL LADDER (find your rung)

1. ⬜ **Rung 1:** Image-first bars *(Level 1)*
2. ⬜ **Rung 2:** Switch schemes on purpose *(Level 2)*

# THE ONE LAW

**Picture first. Rhyme second.**

# THE DAILY PRACTICE SYSTEM

## Level 1 Daily (Beginner) — "Reps"
- **5 min — Count-along:** Count with a beat.
- **10 min — Write 4 bars:** AABB scheme.

# ⬛ LEVEL 1 — FOUNDATIONS (Beginner)

*Goal: write a clean 8-bar verse.*

## Chapter 1: What a Bar Is

One bar = one line.

**Drill 1.1:** Play three songs you love and count the bars out loud.

## Chapter 4: Your First Bars

**Drill 4.1:** Write 4 bars AABB about your street.

## ✅ LEVEL 1 GRADUATION TEST

1. Write an 8-bar verse (AABB or ABAB) on one topic.
2. Perform it to a beat with no stumbles.
3. A friend can say what the verse is about in one sentence.

**Passed? You're at Rung 1. Turn the page.**

---

# ⬛ LEVEL 2 — CRAFT (Intermediate)

*Goal: hear words as vowel patterns.*

## Chapter 6: Vowels Carry the Rhyme

**Drill 6.1 (THE core drill):**
1. Pick a 3-4 syllable phrase.
2. Strip it to vowels only.

# APPENDIX A: THE MULTI-SYLLABLE MATRIX (18 Vowel Patterns)

## A – E (ay – eh)
**2-Syl:** fake friend · state pen · great men

## E – I (ee – eye)
**2-Syl:** sea side · free ride

# APPENDIX F: THE LISTENING CURRICULUM

## Level 1 — Clarity & Story
- Notorious B.I.G. — "Juicy" *(specific life details)*
"""


def click_track(path, bpm, seconds=12, offset=0.13, sr=22050):
    t = np.zeros(int(sr * seconds))
    per = 60 / bpm
    k = 0
    while offset + k * per < seconds:
        s = int((offset + k * per) * sr)
        n = int(0.1 * sr)
        env = np.exp(-np.arange(n) / (0.02 * sr))
        t[s:s + n] += (np.sin(2 * np.pi * (60 if k % 2 == 0 else 200) * np.arange(n) / sr) * env)[:len(t[s:s + n])]
        k += 1
    y = (t / np.abs(t).max() * 0.8 * 32767).astype(np.int16)
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(y.tobytes())


class StationDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        db.init(root / 'station.db')
        academy.init()
        forge.init()
        bible.set_data_dir(root / 'knowledge')

    def tearDown(self):
        self.tmp.cleanup()


class FlowTests(unittest.TestCase):
    def test_parse_sections_speakers_directions(self):
        p = lyrics.parse(VERSE)
        self.assertEqual(p['bars'], 4)
        kinds = [l['kind'] for l in p['sections'][0]['lines']]
        self.assertEqual(kinds[0], 'direction')
        self.assertEqual([l['speaker'] for l in p['sections'][0]['lines'] if l['kind'] == 'bar'], ['DON', 'DON', 'DEMON', 'DEMON'])
        self.assertEqual(lyrics.tempo_hint('Tempo: 90.0 BPM'), 90.0)

    def test_end_rhymes_found_and_grid_placement(self):
        a = flow.analyze(VERSE, 90)
        self.assertGreaterEqual(a['families'], 2)
        bar0, bar1 = a['bars'][0]['syllables'], a['bars'][1]['syllables']
        self.assertIn('rhyme', bar0[-1])
        self.assertEqual(bar0[-1]['rhyme'], bar1[-1]['rhyme'])  # shiver / giver
        for b in a['bars']:
            self.assertTrue(all(0 <= s['step'] < 16 for s in b['syllables']))

    def test_half_time_suggested_for_big_tempo_jump(self):
        c = flow.compare(VERSE, 90, 140)
        self.assertEqual(c['feel'], 'half')
        self.assertLess(c['after']['seconds_per_bar'], 4)
        self.assertEqual(len(c['deltas']), 4)

    def test_crowded_bars_flagged(self):
        dense = 'Malignant delinquent belligerent spitting with venomous elegance relevant evidence'
        a = flow.analyze(dense, 120, pocket=(3, 5))
        self.assertEqual(a['bars'][0]['verdict'], 'crowded')
        self.assertLess(a['bars'][0]['target'], a['bars'][0]['count'])

    def test_numbers_are_spoken(self):
        self.assertIn('five hundred', ' '.join(flow.tokenize('$500 in twenties')))


class BeatTests(unittest.TestCase):
    def test_tempo_and_offset(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'loop.wav'
            click_track(p, 90)
            r = beat.analyze(p, hint_bpm=90)
            self.assertAlmostEqual(r['bpm'], 90, delta=1)
            self.assertAlmostEqual(r['offset'], 0.13, delta=0.03)
            self.assertTrue(r['waveform'])

    def test_pocket_detects_late_takes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'take.wav'
            click_track(p, 360, offset=0.5 + 0.04)  # 16ths at 90 BPM, 40 ms late
            r = beat.pocket(p, 90, offset=0.5)
            self.assertTrue(r['ok'])
            self.assertIn('behind', r['verdict'])


class BibleTests(unittest.TestCase):
    def test_parse_structure(self):
        d = bible.parse(MINI_BIBLE)
        self.assertEqual([l['level'] for l in d['levels']], [1, 2])
        ch = d['levels'][0]['chapters']
        self.assertEqual([c['id'] for c in ch], ['ch-1', 'ch-4'])
        self.assertEqual(ch[0]['drills'][0]['form'], 'reflection')
        self.assertEqual(ch[1]['drills'][0]['scheme'], 'AABB')
        self.assertEqual(d['levels'][1]['chapters'][0]['drills'][0]['form'], 'vowel')
        test = d['levels'][0]['test']
        self.assertEqual(test['parts'][0]['bars'], 8)
        self.assertIn('Rung 1', test['reward_text'])
        self.assertEqual(d['one_law'], 'Picture first. Rhyme second.')
        self.assertEqual(len(d['matrix']), 2)
        self.assertEqual(d['listening'][1]['songs'][0]['title'], 'Juicy')
        self.assertEqual(d['daily'][1]['steps'][0]['minutes'], 5)


class GradingTests(unittest.TestCase):
    def test_scheme_and_vowel_matching(self):
        auto = grading.auto_grade('bars', {'text': VERSE}, 4, 'AABB')
        scheme = [c for c in auto['criteria'] if c['id'] == 'scheme'][0]
        self.assertEqual(scheme['score'], 100)
        self.assertGreater(grading.vowel_match('terrified', 'very high'), 0.75)
        self.assertLess(grading.vowel_match('terrified', 'hello'), 0.5)

    def test_double_stitch_slot_check(self):
        sk = 'Streetlights hollow when the block go dark, I ignite\nShadows follow every step I take, it is midnight'
        auto = grading.auto_grade('skeleton', {'text': sk}, 2)
        self.assertTrue(auto['facts']['pairs'][0]['internal'])

    def test_combine_and_letter(self):
        self.assertEqual(grading.combine({'score': 80}, {'overall': 90})['score'], 86)
        self.assertEqual(grading.combine({'score': 60}, None)['letter'], 'D')


class AcademyTests(StationDB):
    def test_checkin_is_free_and_work_pays(self):
        events = academy.checkin()
        self.assertFalse(any(e['type'] == 'xp' for e in events))
        auto = grading.auto_grade('bars', {'text': VERSE}, 4, 'AABB')
        grade = grading.combine(auto, None)
        sid, events = academy.record_submission('drill-4.1', 'drill', 'bars', {'text': VERSE}, auto, None, grade)
        types = {e['type'] for e in events}
        self.assertTrue({'grade', 'xp', 'achievement', 'rhythm'} <= types)
        self.assertGreater(academy.total_xp(), 0)
        self.assertEqual(len(academy.practice_days()), 1)

    def test_peek_pays_half(self):
        auto = {'score': 90, 'criteria': [], 'facts': {'bars': 0}}
        grade = {'score': 90, 'letter': 'A', 'passed': True}
        _, ev_full = academy.record_submission('a', 'drill', 'bars', {}, auto, None, grade)
        _, ev_peek = academy.record_submission('b', 'drill', 'bars', {}, auto, None, grade, peek=True)
        full = [e['amount'] for e in ev_full if e['type'] == 'xp' and 'a' in e['label'] and 'Passed' in e['label']][0]
        half = [e['amount'] for e in ev_peek if e['type'] == 'xp' and '(peek)' in e['label']][0]
        self.assertLess(half, full)

    def test_rank_progression(self):
        self.assertEqual(academy.rank_for(0)['name'], 'Open Mic Rookie')
        self.assertEqual(academy.rank_for(13000)['name'], 'GOAT Status')
        self.assertAlmostEqual(academy.rank_for(275)['progress'], 0.5, places=2)

    def test_chapter_states_with_bible(self):
        bible.save_source(MINI_BIBLE)
        data = bible.load()
        states, stars = academy.chapter_states(data)
        self.assertEqual(states['ch-1'], 'open')
        self.assertEqual(states['ch-6'], 'peek')


class ForgeTests(StationDB):
    def test_questions_and_trajectory(self):
        q = forge.question_for_page('chapter:ch-1')
        self.assertTrue(q['prompt'])
        self.assertEqual(forge.question_for_page('chapter:ch-1')['id'], q['id'])
        before = forge.fingerprint()
        forge.answer(q['id'], 'We pushed a dead car two miles at 3am laughing the whole way.', q['chips'][0])
        self.assertNotEqual(forge.fingerprint(), before)
        self.assertGreater(forge.trajectory()['choices'], 0)
        self.assertIsNone(forge.question_for_page('chapter:ch-1'))  # answered

    def test_award_is_gated(self):
        with self.assertRaises(ValueError):
            forge.forge('Neon Ledger')

    def test_skill_md_export(self):
        p = {'name': 'Neon Ledger', 'pocket': [3.5, 6.0], 'tagline': 't', 'voice': 'v', 'prompt': 'p',
             'forged': {'imagery': ['glovebox'], 'vocabulary': [], 'never': [], 'fingerprint': 'abc'}}
        md = forge.skill_md(p)
        self.assertTrue(md.startswith('---\nname: neon-ledger-remix'))
        self.assertIn('glovebox', md)


class LLMTests(StationDB):
    def test_keys_masked_and_cleared_on_base_change(self):
        out = llm.update_settings({'provider': 'openai', 'openai': {'preset': 'custom', 'base_url': 'http://127.0.0.1:1234/v1', 'api_key': 'sk-1234567890'}})
        self.assertEqual(out['openai']['api_key'], '')
        self.assertTrue(out['openai']['key_hint'].endswith('7890'))
        out = llm.update_settings({'openai': {'base_url': 'https://evil.example/v1'}})
        self.assertFalse(llm.settings()['openai']['api_key'])

    def test_openai_stream_parsing(self):
        resp = Mock(status_code=200, ok=True)
        resp.iter_lines.return_value = [b'data: {"choices":[{"delta":{"content":"Hel"}}]}', b'', b'data: {"choices":[{"delta":{"content":"lo"}}]}', b'data: [DONE]']
        cfg = llm._merge(llm.DEFAULTS, {'provider': 'openai', 'openai': {'preset': 'custom', 'base_url': 'http://x/v1', 'model': 'm'}})
        with patch('station.llm.requests.post', return_value=resp) as post:
            self.assertEqual(''.join(llm.stream_chat([{'role': 'user', 'content': 'hi'}], 'sys', cfg=cfg)), 'Hello')
            self.assertEqual(post.call_args.kwargs['json']['messages'][0], {'role': 'system', 'content': 'sys'})

    def test_extract_json(self):
        self.assertEqual(llm.extract_json('Sure!\n```json\n{"a": 1}\n```'), {'a': 1})


class JarvisTests(unittest.TestCase):
    def test_action_blocks_split(self):
        text, actions = jarvis.split_actions('Certainly, Sir.\n```action\n{"do":"navigate","to":"academy"}\n```')
        self.assertEqual(text, 'Certainly, Sir.')
        self.assertEqual(actions, [{'do': 'navigate', 'to': 'academy'}])
        self.assertEqual(jarvis.execute(actions[0])['navigate'], '/station/academy')
        self.assertFalse(jarvis.execute({'do': 'rm -rf'})['ok'])

    def test_personas_load(self):
        ids = {p['id'] for p in personas._builtins().values()}
        self.assertTrue({'jarvis', 'coach', 'biggie', 'slim-shady', 'king-von', 'j-cole'} <= ids)
        self.assertEqual(personas.pocket(personas._builtins()['biggie']), (3.0, 5.5))


class ComfyBridgeTests(unittest.TestCase):
    WF = {"1": {"class_type": "LoadImage", "inputs": {"image": "x.png"}, "_meta": {"title": "OF_REFERENCE"}},
          "2": {"class_type": "VHS_LoadVideo", "inputs": {"video": "x.mp4"}, "_meta": {"title": "Load Video"}},
          "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["9", 0]}, "_meta": {"title": "Positive"}},
          "4": {"class_type": "KSampler", "inputs": {"seed": 1, "model": ["8", 0]}, "_meta": {"title": "KSampler"}}}

    def test_locate_tagged_and_guessed_roles(self):
        roles = comfy_bridge.locate(self.WF)
        self.assertEqual(roles['OF_REFERENCE'], '1')
        self.assertEqual(roles['OF_VIDEO'], '2')
        self.assertEqual(roles['OF_PROMPT'], '3')
        self.assertEqual(roles['OF_SEED'], '4')

    def test_wired_inputs_are_not_overwritten(self):
        node = {"inputs": {"text": ["5", 0], "prompt": ""}}
        self.assertTrue(comfy_bridge._set(node, 'hello', 'text'))
        self.assertEqual(node['inputs']['text'], ['5', 0])
        self.assertEqual(node['inputs']['prompt'], 'hello')

    def test_submit_requires_approved_mask(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                comfy_bridge.submit(d, 'p', 'ref.png', 'none.json')


if __name__ == '__main__':
    unittest.main()
