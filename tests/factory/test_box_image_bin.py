import pathlib, re, unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
# Imported lazily, inside functions, on factory-only paths (parallel slots, checkpoint judging);
# never reached by the contestant's bin/setup, bin/reset or bin/check.
FACTORY_ONLY = {"factory_pool", "refusal"}


class BoxImageBinTests(unittest.TestCase):
    def test_every_bench_module_the_box_scripts_import_ships_in_the_box(self):
        """The contestant box runs bin/setup and bin/reset from the bin files the bench image
        copies; a bin module they import that is not copied fails setup with ModuleNotFoundError."""
        shipped = {pathlib.Path(p).name for line in (ROOT / "harbor/images/Dockerfile").read_text().splitlines()
                   if line.startswith("COPY bin/") for p in line.split()[1:-1]}
        missing = set()
        for name in shipped:
            for indent, names, source in re.findall(r"^([ \t]*)(?:import\s+([\w ,]+)|from\s+(\w+)\s+import)",
                                                    (ROOT / "bin" / name).read_text(), re.M):
                for module in filter(None, (m.split(" as ")[0].strip() for m in (names or source).split(","))):
                    local = (ROOT / "bin" / f"{module}.py").is_file()
                    if local and f"{module}.py" not in shipped and not (indent and module in FACTORY_ONLY):
                        missing.add(module)
        self.assertEqual(missing, set())


if __name__ == "__main__":
    unittest.main()
