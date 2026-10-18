import { mount, unmount } from "svelte";
import CsvEditor from "./CsvEditor.svelte";

let current = null;

window.VotilioCsv = {
  /** Mounts a fresh editor into `el`. `opts`: {kind, endpoint, template, csrf, positions}. */
  open(el, opts, onDone) {
    if (current) {
      try { unmount(current); } catch (e) { /* already gone */ }
      current = null;
    }
    el.innerHTML = "";
    current = mount(CsvEditor, { target: el, props: { opts, onDone } });
  },
};
