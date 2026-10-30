from compiler_agent.lexer import Lexer, TokenType
from compiler_agent.parser import Parser, ParserError
from compiler_agent.semantic_analyzer import SemanticAnalyzer, SemanticError
from compiler_agent.ir_generator import generate_ir
from compiler_agent.ast_nodes import IfNode, RepeatNode
from compiler_agent.agent import Agent, CompilationError
from compiler_agent.speech import normalize_transcript, is_exit, is_yes
from compiler_agent.registry import resolve_app, normalize_keys
from compiler_agent.backends import find_text_box


def parse(cmd):
    return Parser(Lexer(cmd).tokenize()).parse()


def analyze(cmd):
    return SemanticAnalyzer().analyze(parse(cmd))


def compile_ir(cmd):
    return Agent(dry_run=True, echo=False).compile(cmd)


def ops(cmd):
    return [op["op"] for op in compile_ir(cmd)]


def raises(exc, fn, *a):
    try:
        fn(*a)
    except exc:
        return True
    assert False, f"expected {exc.__name__}"


def test_lexer_basic():
    tokens = Lexer('open Word').tokenize()
    types = [t.type for t in tokens]
    assert types == [TokenType.VERB, TokenType.IDENTIFIER, TokenType.EOF]


def test_lexer_quoted_string_not_split():
    tokens = Lexer('type "hello world foo"').tokenize()
    strings = [t.value for t in tokens if t.type == TokenType.STRING]
    assert strings == ["hello world foo"]


def test_parser_multi_action():
    tokens = Lexer("open word and take a screenshot").tokenize()
    program = Parser(tokens).parse()
    assert len(program.actions) == 2
    assert program.actions[0].verb == "OPEN_APP"
    assert program.actions[0].target == "word"
    assert program.actions[1].verb == "SCREENSHOT"


def test_parser_rejects_garbage():
    raises(ParserError, parse, "blorp fnord")


def test_semantic_requires_text_for_type():
    raises(SemanticError, analyze, "type")


def test_semantic_paste_needs_prior_copy():
    raises(SemanticError, analyze, "paste into word")


def test_ir_shape():
    program = analyze('create notes.txt')
    ir = generate_ir(program)
    assert ir == [{"op": "CREATE_FILE", "target": "notes.txt", "args": {}}]


def test_full_pipeline_dry_run():
    agent = Agent(dry_run=True, echo=False)
    results = agent.run('take a screenshot and paste it into the word document')
    assert len(results) == 3
    assert [op["op"] for op in agent.last.ir] == ["SCREENSHOT", "SWITCH_APP", "PASTE"]


def test_full_pipeline_catches_bad_command():
    agent = Agent(dry_run=True, echo=False)
    raises(CompilationError, agent.run, "paste into word")


def test_dictation_without_quotes():
    program = parse("open notepad and type hello world, this is great and save")
    assert [a.verb for a in program.actions] == ["OPEN_APP", "TYPE_TEXT", "SAVE_FILE"]
    assert program.actions[1].args["text"] == "hello world, this is great"


def test_dictation_keeps_command_words_inside_text():
    program = parse("type please open the door")
    assert len(program.actions) == 1
    assert program.actions[0].args["text"] == "please open the door"


def test_spoken_quote_marks():
    program = parse("type quote delete everything and close word unquote and save")
    assert program.actions[0].args["text"] == "delete everything and close word"
    assert program.actions[1].verb == "SAVE_FILE"


def test_sentence_punctuation_from_speech_engines():
    program = parse("Open Notepad. Then type hello world. How are you? Open Chrome.")
    assert [a.verb for a in program.actions] == ["OPEN_APP", "TYPE_TEXT", "OPEN_APP"]
    assert program.actions[1].args["text"] == "hello world. How are you"


def test_implicit_connector_between_commands():
    program = parse("open notepad type hello")
    assert [a.verb for a in program.actions] == ["OPEN_APP", "TYPE_TEXT"]


def test_noun_use_of_command_word():
    program = parse("paste the screenshot into word")
    assert len(program.actions) == 1
    assert program.actions[0].target == "word"


def test_number_words_and_compound_numbers():
    tokens = Lexer("wait twenty five seconds").tokenize()
    assert [t.value for t in tokens if t.type == TokenType.NUMBER] == [25]


def test_postfix_repeat():
    program = parse("press tab 3 times")
    assert isinstance(program.statements[0], RepeatNode)
    assert program.statements[0].count == 3


def test_twice_is_a_repeat():
    program = parse("scroll down twice")
    assert isinstance(program.statements[0], RepeatNode)
    assert program.statements[0].count == 2


def test_repeat_block_grammar():
    program = parse("repeat three times press tab and type hi end repeat and save")
    loop = program.statements[0]
    assert isinstance(loop, RepeatNode) and loop.count == 3 and len(loop.body) == 2
    assert program.statements[1].verb == "SAVE_FILE"


def test_if_else_grammar():
    program = parse("if notes.txt does not exist then create notes.txt otherwise delete notes.txt end if and open notepad")
    node = program.statements[0]
    assert isinstance(node, IfNode)
    assert node.condition.kind == "EXISTS" and node.condition.negated
    assert node.then_body[0].verb == "CREATE_FILE"
    assert node.else_body[0].verb == "DELETE_FILE"
    assert program.statements[1].verb == "OPEN_APP"


def test_if_app_is_open_condition():
    node = parse("if chrome is open then close chrome").statements[0]
    assert node.condition.kind == "RUNNING"


def test_dangling_otherwise_rejected():
    raises(ParserError, parse, "open notepad otherwise close notepad")


def test_app_alias_resolution():
    assert resolve_app("microsoft word") == "word"
    assert resolve_app("note pad") == "notepad"
    assert resolve_app("google chrome") == "chrome"
    assert resolve_app("notpad") == "notepad"
    assert resolve_app("blorp") is None


def test_open_website_becomes_open_url():
    ir = compile_ir("open youtube")
    assert ir[0]["op"] == "OPEN_URL" and ir[0]["args"]["url"] == "https://www.youtube.com"
    ir = compile_ir("go to github.com")
    assert ir[0]["args"]["url"] == "https://github.com"


def test_open_file_becomes_open_file():
    assert ops("open report.pdf") == ["OPEN_FILE"]


def test_go_to_app_becomes_switch():
    assert ops("go to word") == ["SWITCH_APP"]


def test_keys_normalized():
    assert normalize_keys(["control", "shift", "escape"]) == ["ctrl", "shift", "esc"]
    assert normalize_keys(["page", "down"]) == ["pagedown"]
    assert normalize_keys(["ctrl+s"]) == ["ctrl", "s"]
    raises(ValueError, normalize_keys, ["banana"])


def test_press_unknown_key_is_semantic_error():
    raises(SemanticError, analyze, "press control banana")


def test_delete_twice_is_semantic_error():
    raises(SemanticError, analyze, "delete a.txt and delete a.txt")


def test_delete_wildcard_rejected():
    raises(SemanticError, analyze, "delete *.txt")


def test_repeat_bound_checked():
    raises(SemanticError, analyze, "repeat 100 times press tab")


def test_wait_units_and_limit():
    assert compile_ir("wait 1 minute")[0]["args"]["seconds"] == 60
    raises(SemanticError, analyze, "wait 10 minutes")


def test_switch_to_closed_app_rejected():
    raises(SemanticError, analyze, "close word and switch to word")


def test_paste_dataflow_merges_branches():
    analyze("if x.txt exists then copy otherwise take a screenshot end if and paste into word")
    raises(SemanticError, analyze, "if x.txt exists then copy end if and paste into word")


def test_paste_inside_loop_after_copy_is_valid():
    analyze("copy and repeat 3 times paste into notepad")


def test_constant_folding_removes_branch():
    assert ops('create zz_a.txt and if zz_a.txt exists then type "yes" otherwise type "no"') == ["CREATE_FILE", "TYPE_TEXT"]


def test_unknown_condition_kept_as_jumps():
    assert ops("if zz_missing_file.txt exists then copy") == ["TEST", "JUMP_IF_FALSE", "COPY", "LABEL"]


def test_small_loop_unrolled():
    assert ops("press tab 3 times") == ["PRESS", "PRESS", "PRESS"]


def test_large_loop_stays_a_loop():
    assert ops("press down 20 times") == ["LOOP_INIT", "LABEL", "PRESS", "LOOP_NEXT"]


def test_redundant_switch_removed():
    assert ops("open notepad and copy and paste into notepad") == ["OPEN_APP", "COPY", "PASTE"]


def test_switch_kept_when_needed():
    assert ops("take a screenshot and paste it into word") == ["SCREENSHOT", "SWITCH_APP", "PASTE"]


def test_waits_merged():
    ir = compile_ir("wait 2 seconds and wait 3 seconds")
    assert len(ir) == 1 and ir[0]["args"]["seconds"] == 5


def test_optimizer_can_be_disabled():
    agent = Agent(dry_run=True, optimize=False, echo=False)
    assert [op["op"] for op in agent.compile("press tab 3 times")] == ["LOOP_INIT", "LABEL", "PRESS", "LOOP_NEXT"]


def test_vm_runs_else_branch():
    agent = Agent(dry_run=True, echo=False)
    results = agent.run("if zz_missing_file.txt exists then type yes otherwise type no")
    assert results == ["Would type: 'no'"]


def test_vm_runs_loop_count():
    agent = Agent(dry_run=True, echo=False)
    assert len(agent.run("press down 20 times")) == 20


def test_vm_nested_loops():
    agent = Agent(dry_run=True, echo=False)
    results = agent.run("repeat 10 times press down and repeat 10 times press tab end repeat end repeat")
    assert len(results) == 110


def test_dry_run_simulates_file_system():
    agent = Agent(dry_run=True, optimize=False, echo=False)
    results = agent.run('create zz_sim.txt and if zz_sim.txt exists then type "seen"')
    assert results[-1] == "Would type: 'seen'"


def test_confirmation_can_block_delete():
    agent = Agent(dry_run=True, echo=False, confirm=lambda description: False)
    results = agent.run("create zz_c.txt and delete zz_c.txt")
    assert results[1].startswith("Skipped")


def test_session_clipboard_across_commands():
    agent = Agent(dry_run=True, echo=False)
    agent.run("take a screenshot")
    assert len(agent.run("paste it into word")) == 2


def test_transcript_normalization():
    assert normalize_transcript("Hey computer, create notes dot txt.") == "create notes.txt"
    assert normalize_transcript("open my underscore file dot py") == "open my_file.py"
    assert is_exit("Stop listening.")
    assert is_yes("Yes please") and not is_yes("no")


def test_create_word_document_with_title():
    ir = compile_ir('create a word file with title as "ASISH"')
    assert [op["op"] for op in ir] == ["OPEN_APP", "WAIT", "TYPE_TEXT", "PRESS"]
    assert ir[0]["args"]["app"] == "word"
    assert ir[2]["args"]["text"] == "ASISH"


def test_create_word_document_named_with_title():
    ir = compile_ir('create a word document called report with title "Compiler Project"')
    assert [op["op"] for op in ir] == ["OPEN_APP", "WAIT", "TYPE_TEXT", "PRESS", "SAVE_FILE"]
    assert ir[2]["args"]["text"] == "Compiler Project"
    assert ir[4]["target"] == "report"


def test_unquoted_title_and_name():
    ir = compile_ir("create a word document called report with title compiler design project")
    assert ir[2]["args"]["text"] == "compiler design project"
    assert ir[-1]["op"] == "SAVE_FILE" and ir[-1]["target"] == "report"


def test_open_then_create_document_opens_once():
    assert ops('open word and create a word file with title "ASISH"').count("OPEN_APP") == 1


def test_close_all_google_tabs_closes_chrome():
    ir = compile_ir("close all google tab")
    assert ir[0]["op"] == "CLOSE_APP" and ir[0]["args"]["app"] == "chrome"
    assert compile_ir("close all tabs")[0]["args"]["app"] == "chrome"


def test_close_one_tab_presses_ctrl_w():
    ir = compile_ir("close this tab")
    assert ir[0]["op"] == "PRESS" and ir[0]["args"]["keys"] == ["ctrl", "w"]
    assert "destructive" not in ir[0]["args"]


def test_plain_file_still_created():
    assert ops("create notes.txt") == ["CREATE_FILE"]


def test_add_title_into_app():
    ir = compile_ir("open word and add title as ASISH in word")
    assert [op["op"] for op in ir] == ["OPEN_APP", "TYPE_TEXT"]
    assert ir[1]["args"]["text"] == "ASISH"


def test_add_quoted_title():
    program = parse('add title "ASISH"')
    assert program.actions[0].args["text"] == "ASISH"


def test_ocr_box_finder():
    data = {
        "text": ["File", "Save", "As", "Save"],
        "conf": [90, 50, 90, 95],
        "left": [0, 100, 140, 300],
        "top": [0, 10, 10, 50],
        "width": [30, 30, 20, 30],
        "height": [10, 10, 10, 10],
    }
    assert find_text_box(data, "save") == (315.0, 55.0)
    assert find_text_box(data, "save as") == (130.0, 15.0)
    assert find_text_box(data, "print") is None


if __name__ == "__main__":
    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_")]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL  {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
