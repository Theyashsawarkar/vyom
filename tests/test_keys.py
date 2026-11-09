"""vyom/keys.py: tokens, sequences, counts, which-key lists, annotations.
Pure Python: `python3 -m unittest discover tests` (no GTK needed)."""
import importlib.util
import pathlib
import unittest

spec = importlib.util.spec_from_file_location("keys", pathlib.Path(__file__).parent.parent / "vyom" / "keys.py")
K = importlib.util.module_from_spec(spec)
spec.loader.exec_module(K)
B = K.Bind


def feed(km, seq, machine=None, counts=True):
    m = machine or K.Machine()
    out = None
    for tok in K.tokens(seq):
        out = m.feed(km, tok, counts=counts)
    return out


class Tokens(unittest.TestCase):
    def test_token(self):
        t = K.token
        self.assertEqual(t("j", set()), "j")
        self.assertEqual(t("G", {"shift"}), "G")
        self.assertEqual(t("g", {"shift"}), "G")          # a virtual keyboard's G
        self.assertEqual(t("space", set()), " ")
        self.assertEqual(t("question", {"shift"}), "?")
        self.assertEqual(t("d", {"ctrl"}), "<C-d>")
        self.assertEqual(t("Return", set()), "<CR>")
        self.assertEqual(t("Return", {"shift"}), "<S-CR>")
        self.assertEqual(t("Return", {"ctrl"}), "<C-CR>")
        self.assertEqual(t("ISO_Left_Tab", {"shift"}), "<S-Tab>")
        self.assertEqual(t("KP_5", set()), "5")
        self.assertEqual(t("1", {"alt"}), "<A-1>")
        self.assertEqual(t("F11", set()), "<F11>")
        self.assertIsNone(t("Super_L", set()))

    def test_spell(self):
        self.assertEqual(K.spell(" tc"), "Space t c")
        self.assertEqual(K.spell("  "), "Space Space")
        self.assertEqual(K.spell("gg"), "g g")
        self.assertEqual(K.spell("<C-d>"), "Ctrl+d")
        self.assertEqual(K.spell("<S-CR>"), "Shift+Enter")
        self.assertEqual(K.spell("<S-Tab>"), "Shift+Tab")
        self.assertEqual(K.tokens(" y<CR>x"), [" ", "y", "<CR>", "x"])
        self.assertEqual(K.tokens("<"), ["<"])

    def test_modifiers(self):
        self.assertTrue(K.is_modifier("Shift_L"))
        self.assertTrue(K.is_modifier("Control_R"))
        self.assertFalse(K.is_modifier("s"))


class Machine(unittest.TestCase):
    km = K.Keymap([B("j", "down", "Move down"), B("gg", "top", "Jump to the top"),
                   B(" yy", "copy", "Copy the name"), B(" yi", "copy:id", "Copy the ID"),
                   B("1", "dock", "Open the first dock app")])

    def test_count(self):
        r = feed(self.km, "5j")
        self.assertEqual((r.kind, r.bind.seq, r.count), ("run", "j", 5))

    def test_sequence(self):
        m = K.Machine()
        self.assertEqual(m.feed(self.km, "g").kind, "pending")
        self.assertEqual(m.typed(), "g")
        r = m.feed(self.km, "g")
        self.assertEqual((r.kind, r.bind.seq), ("run", "gg"))
        self.assertFalse(m.busy())

    def test_leader_with_count(self):
        r = feed(self.km, "3 yi")
        self.assertEqual((r.bind.action, r.count), ("copy:id", 3))

    def test_exact_digit_beats_count(self):
        self.assertEqual(feed(self.km, "1").bind.action, "dock")
        r = feed(self.km, "21j")              # a count already started: a bound digit keeps counting
        self.assertEqual((r.bind.seq, r.count), ("j", 21))

    def test_zero_is_not_a_count_first(self):
        km = K.Keymap([B("0", "start", "Jump to the start"), B("j", "down", "Move down")])
        self.assertEqual(feed(km, "0").bind.action, "start")
        self.assertEqual(feed(km, "10j").count, 10)

    def test_counts_off(self):
        r = feed(self.km, "5", counts=False)
        self.assertEqual(r.kind, "unknown")

    def test_escape_cancels(self):
        m = K.Machine()
        m.feed(self.km, " ")
        self.assertEqual(m.feed(self.km, "<Esc>").kind, "cancel")
        self.assertFalse(m.busy())

    def test_unknown(self):
        r = feed(self.km, " q")
        self.assertEqual((r.kind, r.seq), ("unknown", " q"))


class Lists(unittest.TestCase):
    def test_next_keys(self):
        km = K.Keymap([B(" yy", "c", "Copy the name"), B(" yi", "c", "Copy the ID"), B(" r", "r", "Reload"),
                       B(" x", "h", "Hidden", hidden=True)], groups={" c": "container"})
        top = {t: w for t, w, _ in km.next_keys(" ")}
        self.assertEqual(top, {"y": "copy…", "r": "Reload"})
        self.assertEqual([t for t, _, _ in km.next_keys(" y")], ["y", "i"])

    def test_later_bind_wins(self):
        km = K.Keymap([B(" r", "refresh", "Reload"), B(" r", "rates", "Update the rates")])
        self.assertEqual(km.table[" r"].action, "rates")

    def test_applies(self):
        b = B("<CR>", "run", "Run", mode="insert", when="calc")
        self.assertTrue(b.applies("insert", "calc"))
        self.assertFalse(b.applies("insert", "convert"))
        self.assertFalse(b.applies("normal", "calc"))
        self.assertTrue(B("q", "x", "Quit", mode="any").applies("insert"))

    def test_help_and_palette(self):
        km = K.Keymap([B("j", "d", "Move down"), B(" yy", "c", "Copy the name"), B(" r", "r", "Reload")])
        names = [n for n, _ in K.help_rows(km)]
        self.assertEqual(names, ["Keys", "Leader", "Space y · copy"])
        rows = K.palette_rows(km)
        self.assertEqual(rows[0][0], "Space r")
        self.assertTrue(K.fuzzy("cop name", "Copy the name Space y y"))
        self.assertFalse(K.fuzzy("name copy", "Copy the name"))

    def test_annotations(self):
        lines = K.annotations("Vyom", [("ganit", "normal", [B(" yy", "c", "Copy the answer"),
                                                           B("x", "h", "", hidden=True)])])
        self.assertEqual(lines, ["# keybind: Vyom/ganit:normal | Space y y | Copy the answer"])

    def test_reserved_groups(self):
        self.assertEqual(K.misused_groups([], {" f": "fullscreen", " c": "container"}),
                         [(" f", "fullscreen", "find")])
        self.assertEqual(K.RESERVED & K.FREE, set())


if __name__ == "__main__":
    unittest.main()


class BareAngleBracket(unittest.TestCase):
    def test_lt_is_its_own_key(self):
        km = K.Keymap([K.Bind("<", "prev", "Go back"), K.Bind("<CR>", "ok", "Open it")])
        self.assertEqual(K.tokens("<"), ["<"])
        self.assertEqual(K.tokens(" y<CR>"), [" ", "y", "<CR>"])
        exact, longer = km.lookup("<")
        self.assertEqual(exact.action, "prev")
        self.assertFalse(longer)


class CtrlAngleBrackets(unittest.TestCase):
    def test_ctrl_lt_and_gt_are_one_token(self):
        self.assertEqual(K.tokens("<C-<>"), ["<C-<>"])
        self.assertEqual(K.tokens("<C->>"), ["<C->>"])
        self.assertEqual(K.tokens("<<C-<>"), ["<", "<C-<>"])
        km = K.Keymap([K.Bind("<", "prev", "Go back"), K.Bind("<C-<>", "far", "Go far back")])
        exact, longer = km.lookup("<")
        self.assertEqual(exact.action, "prev")
        self.assertFalse(longer)
