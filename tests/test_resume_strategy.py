import copy,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from strategy_fixture import fixture,ROOT
sys.path.insert(0,str(ROOT/'scripts'))
import render_editorial as red
import validate_report as vr


class StrategyContractTests(unittest.TestCase):
    def setUp(self):self.report,self.ed=fixture();self.s=self.ed['resume_strategy']
    def errors(self):return red.validate_editorial(self.report,self.ed)
    def rejected(self,fragment):
        errors=self.errors();self.assertTrue(any(fragment in e for e in errors),errors)
    def test_valid_and_score_unchanged(self):
        self.assertEqual(self.errors(),[]);self.assertEqual(vr.check_report(self.report),[])
        before=[j['score'] for j in self.report['jobs']];red.render_editorial_report(self.report,self.ed)
        self.assertEqual([j['score'] for j in self.report['jobs']],before)
    def test_missing_strategy(self):del self.ed['resume_strategy'];self.rejected('resume_strategy')
    def test_missing_member(self):del self.ed['member_card'];self.rejected('member_card')
    def test_required_nested_fields(self):
        for field in list(self.s):
            with self.subTest(field=field):
                r,e=fixture();del e['resume_strategy'][field]
                self.assertTrue(red.validate_editorial(r,e))
    def test_wrong_type_has_clean_cli_error(self):
        self.s['inventory']='wrong'
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'ed.json').write_text(json.dumps(self.ed));(p/'rep.json').write_text(json.dumps(self.report))
            c=subprocess.run([sys.executable,str(ROOT/'scripts/render_editorial.py'),'--input',str(p/'rep.json'),'--editorial',str(p/'ed.json'),'--outdir',str(p/'out')],capture_output=True,text=True)
            self.assertEqual(c.returncode,1);self.assertIn('契约校验失败',c.stderr);self.assertNotIn('Traceback',c.stderr);self.assertFalse((p/'out').exists())
    def test_unknown_nested_key(self):self.s['inventory'][0]['ats_score']=100;self.rejected('未定义字段')
    def test_unhashable_version_returns_error(self):
        for value in [[],{}]:
            self.ed['editorial_version']=value;self.rejected('string')
    def test_non_object_editorial_returns_error(self):
        self.assertTrue(red.validate_editorial(self.report,[]))
    def test_bad_enum(self):self.s['inventory'][0]['disposition']='magic';self.rejected('枚举')
    def test_bad_pattern(self):self.s['inventory'][0]['item_id']='not-an-id';self.rejected('pattern')
    def test_empty_label(self):self.s['inventory'][0]['label']='';self.rejected('minLength')
    def test_empty_inventory(self):self.s['inventory']=[];self.rejected('minItems')
    def test_too_many_focus(self):self.s['job_focus']*=4;self.rejected('maxItems')
    def test_unknown_parent(self):self.s['inventory'][1]['parent_id']='item-absent';self.rejected('父级')
    def test_duplicate_id(self):self.s['inventory'][1]['item_id']=self.s['inventory'][0]['item_id'];self.rejected('重复')
    def test_duplicate_original_order(self):self.s['inventory'][3]['original_order']=1;self.rejected('原始顺序')
    def test_quote_must_be_verbatim(self):self.s['inventory'][0]['raw_quote']='不存在的引文';self.rejected('逐字')
    def test_unknown_evidence(self):self.s['inventory'][0]['evidence_ids']=['ev-absent'];self.rejected('证据')
    def test_wrong_job(self):self.s['job_id']='job-absent';self.rejected('主目标')
    def test_missing_blueprint_item(self):self.s['blueprint'][0]['entries'][0]['bullet_ids'].pop();self.rejected('遗漏')
    def test_omit_cannot_stay_in_blueprint(self):self.s['inventory'][0]['disposition']='omit';self.rejected('删除项')
    def test_work_header_cannot_be_omitted(self):next(x for x in self.s['inventory'] if x.get('entry_kind')=='work')['disposition']='omit';self.rejected('任职')
    def test_bullet_cannot_move_between_entries(self):
        self.s['blueprint'][0]['entries'][0]['bullet_ids'].append(self.s['blueprint'][1]['entries'][0]['bullet_ids'].pop());self.rejected('跨经历')
    def test_business_problem_not_fact(self):self.s['job_focus'][0]['business_problem']['basis']='fact';self.rejected('招聘业务问题')
    def test_unanchored_claim(self):self.s['experience_insights'][0]['problem']['item_ids']=[];self.rejected('锚点')
    def test_invented_metric(self):self.s['experience_insights'][0]['impact']['text']='收入提升 99%';self.s['experience_insights'][0]['impact']['basis']='fact';self.rejected('数字')
    def test_scope_word_not_borrowed_from_jd(self):
        c=self.s['experience_insights'][0]['role'];c['text']='主导所有项目';c['basis']='fact';c['req_ids']=[self.report['requirements'][0]['req_id']];c['evidence_ids']=next(x['evidence_ids'] for x in self.s['inventory'] if x.get('entry_kind')=='work');self.rejected('职责范围词')
    def test_scope_negation_cannot_bypass_fact_guard(self):
        c=self.s['experience_insights'][0]['role'];c.update(basis='fact',evidence_ids=next(x['evidence_ids'] for x in self.s['inventory'] if x.get('entry_kind')=='work'))
        for text in ['并非没有声明独立完成。','不是未写明主导该事项。','没有声明独立完成这件事是假的。']:
            with self.subTest(text=text):c['text']=text;self.rejected('职责范围词')
    def test_unknown_scope_can_be_question(self):
        c=self.s['experience_insights'][0]['role'];c.update(text='是否曾独立完成上述工作，需要核实职责范围。',basis='question')
        self.assertEqual(self.errors(),[])
    def test_cross_entry_fact(self):
        education=next(x for x in self.s['inventory'] if x.get('entry_kind')=='education');self.s['experience_insights'][0]['role']['evidence_ids']=education['evidence_ids'];self.rejected('跨经历')
    def test_answer_requires_entry_link(self):
        self.report['answers']=[{'answer_id':'ans-test','question':'本人角色？','answer':'参与交付。','recorded_as':'supplementary_evidence','applies_to_jobs':['job-1']}];self.s['experience_insights'][0]['role']['answer_ids']=['ans-test'];self.rejected('answer_links')
    def test_answer_link_can_supply_fact(self):
        self.report['answers']=[{'answer_id':'ans-test','question':'本人角色？','answer':'负责整理。','recorded_as':'supplementary_evidence','applies_to_jobs':['job-1']}];c=self.s['experience_insights'][0]['role'];c.update(text='负责整理。',basis='fact',answer_ids=['ans-test']);self.s['answer_links']=[{'answer_id':'ans-test','entry_id':self.s['experience_insights'][0]['entry_id']}];self.assertEqual(self.errors(),[])
    def test_no_visual_claim_without_visual_input(self):
        self.s['ats_review']['format_observations']=[{'text':'使用了双栏布局。','basis':'fact','req_ids':[],'evidence_ids':[self.report['evidence'][0]['evidence_id']],'answer_ids':[],'item_ids':[]}];self.rejected('未见原始视觉')
    def test_all_rewrites_need_location(self):self.s['revision_priorities'][0]['rewrite_ids']=[];self.rejected('全部有效改写')
    def test_after_override_uses_same_entry_pool(self):self.ed['rewrites'][0]['after_text']='完成 999 项项目';self.rejected('数字')
    def test_structural_revision_may_reference_other_entries(self):
        edu=next(x for x in self.s['inventory'] if x.get('entry_kind')=='education')
        self.s['revision_priorities'][0]['location_item_ids'].append(edu['item_id'])
        self.assertEqual(self.errors(),[], '改写归属由保留原条目唯一确定；结构建议可涉及其他经历')
    def test_duplicate_original_in_two_entries_is_ambiguous(self):
        target=self.report['rewrites'][0]['original_quote'];work=self.s['revision_priorities'][0]['location_item_ids'][0]
        edu=next(x for x in self.s['inventory'] if x['kind']=='bullet' and x['item_id']!=work)
        eid=edu['evidence_ids'][0];next(x for x in self.report['evidence'] if x['evidence_id']==eid)['quote']=target
        edu.update(raw_quote=target,label=target)
        self.s['revision_priorities'][0]['location_item_ids'].append(edu['item_id']);self.rejected('唯一的所属经历')
    def test_new_inventory_ids_do_not_leak_into_visible_text(self):self.s['inventory'][0]['rationale']='前置 item-test-1';self.rejected('机器标识')
    def test_rewrite_cannot_target_omitted_bullet(self):
        rid=self.s['revision_priorities'][0]['location_item_ids'][0]
        next(x for x in self.s['inventory'] if x['item_id']==rid)['disposition']='omit'
        self.s['blueprint'][0]['entries'][0]['bullet_ids'].remove(rid);self.rejected('已删除项')
    def test_concern_needs_resume_and_location(self):
        c={'text':'这段任职可能需要解释。','basis':'inference','req_ids':[self.report['requirements'][0]['req_id']],'evidence_ids':[],'answer_ids':[],'item_ids':[]}
        self.s['recruiter_review']['concerns']=[{'observation':c,'interview_question':'本人做了什么？','change':'写清本人角色。'}];self.rejected('筛选疑虑')
    def test_numbers_in_inventory_rationale_need_source(self):self.s['inventory'][0]['rationale']='增加 999 项成果';self.rejected('数字')
    def test_keywords_claiming_equivalence_need_resume(self):
        c=self.s['job_focus'][0]['business_problem'].copy()
        self.s['ats_review']['keywords']=[{'concept':'工具使用','req_ids':c['req_ids'],'status':'equivalent','observation':c}];self.rejected('声称已有')
    def test_short_employment_quote_rejected(self):
        work=next(x for x in self.s['inventory'] if x.get('entry_kind')=='work');work['raw_quote']='用户运营专员';self.rejected('完整任职')
    def test_contact_cannot_enter_inventory(self):
        q='邮箱 contact@example.com';self.report['evidence'][0]['quote']=q;self.s['inventory'][0].update(label=q,raw_quote=q);self.rejected('联系方式')
    def test_voice_pairing(self):self.ed['voice_version']='jd-match-voice/0.2.0';self.rejected('voice_version')
    def test_old_version_cannot_silently_ignore_strategy(self):self.ed['editorial_version']='jd-match-editorial/0.2.0';self.ed['voice_version']='jd-match-voice/0.2.0';self.rejected('仅用于')


class SyntheticModelAcceptanceTests(unittest.TestCase):
    def test_three_model_artifacts_validate_and_cover_body(self):
        for name in ['education-first-work','older-relevant-work','freshgrad-project']:
            with self.subTest(case=name):
                p=ROOT/'examples/strategy-upgrade'/name
                r=json.loads((p/'report.json').read_text());e=json.loads((p/'editorial.json').read_text())
                self.assertTrue(r['synthetic']);self.assertEqual(vr.check_report(r),[]);self.assertEqual(red.validate_editorial(r,e),[])
                refs={eid for item in e['resume_strategy']['inventory'] for eid in item['evidence_ids']}
                pool='\n'.join(x['quote'] for x in r['evidence'] if x['evidence_id'] in refs)
                for line in (p/'resume.md').read_text().splitlines():
                    if line.strip() and not line.startswith(('# ','>')):self.assertIn(line.removeprefix('## ').removeprefix('- '),pool)
    def test_older_relevant_entry_precedes_recent_job(self):
        p=ROOT/'examples/strategy-upgrade/older-relevant-work';e=json.loads((p/'editorial.json').read_text());s=e['resume_strategy'];items={x['item_id']:x for x in s['inventory']}
        work=next(x for x in s['blueprint'] if items[x['section_id']]['label']=='工作经历')
        self.assertIn('2020.01',items[work['entries'][0]['entry_id']]['raw_quote'])
        self.assertIn('2023.01',items[work['entries'][1]['entry_id']]['raw_quote'])
        team=next(x for x in items.values() if '团队活动参与率' in x['raw_quote'])
        self.assertIn('团队',team['raw_quote'])
    def test_freshgrad_project_precedes_education_for_data_role(self):
        p=ROOT/'examples/strategy-upgrade/freshgrad-project';s=json.loads((p/'editorial.json').read_text())['resume_strategy'];items={x['item_id']:x for x in s['inventory']}
        self.assertEqual(items[s['blueprint'][0]['section_id']]['label'],'项目经历')
    def test_primary_switch_rebuilds_strategy_and_keeps_scores(self):
        p=ROOT/'examples/strategy-upgrade/freshgrad-project-research'
        r=json.loads((p/'report.json').read_text());e=json.loads((p/'editorial.json').read_text());s=e['resume_strategy'];items={x['item_id']:x for x in s['inventory']}
        self.assertEqual(s['job_id'],'job-2');self.assertEqual(red.validate_editorial(r,e),[]);self.assertEqual(vr.check_report(r),[])
        self.assertEqual(items[s['blueprint'][0]['section_id']]['label'],'教育背景')
        original=json.loads((p.with_name('freshgrad-project')/'report.json').read_text())
        self.assertEqual({j['job_id']:j['score'] for j in r['jobs']},{j['job_id']:j['score'] for j in original['jobs']})


class StrategyRenderingTests(unittest.TestCase):
    def setUp(self):self.report,self.ed=fixture()
    def test_strategy_precedes_rewrites_and_numbering(self):
        h=red.render_editorial_report(self.report,self.ed)
        self.assertLess(h.index('id="section-strategy"'),h.index('id="section-rewrites"'))
        self.assertIn('6. 证据详情',h);self.assertIn('建议结构 · 从上到下',h)
        self.assertIn('details-accordion',h);self.assertIn('原始视觉版式未核验',h)
    def test_redaction_and_escaping_in_new_content(self):
        self.ed['resume_strategy']['inventory'][0]['label']='<script>alert</script> 教育背景'
        h=red.render_editorial_report(self.report,self.ed)
        self.assertIn('&lt;script&gt;alert&lt;/script&gt;',h);self.assertNotIn('合成院校',h)
    def test_new_strategy_not_embedded_in_shared_assets(self):
        self.ed['resume_strategy']['inventory'][0]['rationale']='仅限报告的盘点信息'
        with tempfile.TemporaryDirectory() as t:
            m=red.generate_bundle(self.report,self.ed,Path(t));self.assertIsNotNone(m['member_card'])
            for p in [m['member_card'],m['social'],m['preview']]+m['cards']:
                self.assertNotIn('仅限报告的盘点信息',p.read_text())
    def test_short_work_label_keeps_original_employment_header(self):
        work=next(x for x in self.ed['resume_strategy']['inventory'] if x.get('entry_kind')=='work');work['label']='相关工作经历'
        self.assertEqual(red.validate_editorial(self.report,self.ed),[])
        h=red.render_editorial_report(self.report,self.ed)
        self.assertIn('任职信息：某机构甲 · 用户运营专员 · 2021.01–2026.09',h)
    def test_v2_remains_byte_identical(self):
        p=ROOT/'examples/case-a-freshgrad-ops';r=json.loads((p/'expected.json').read_text());e=json.loads((p/'editorial.json').read_text());h=red.render_editorial_report(r,e)
        self.assertNotIn('section-strategy',h)
        self.assertEqual(red.validate_editorial(r,e),[])
        import hashlib
        self.assertEqual(hashlib.sha256(h.encode()).hexdigest(), '76f9bbb3b606ba9de875b5b871615dcabdbfbce754bdfe2b5c050eac1d0cf030')


if __name__=='__main__':unittest.main()
