// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package settings

import (
	"encoding/json"
	"fmt"
	"io"
	"math"
	"os"
	"sort"
	"strconv"
	"strings"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/tui"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
	"github.com/kovidgoyal/kitty/tools/tui/readline"
	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

type Setting struct {
	Name      string   `json:"name"`
	Group     []string `json:"group"`
	Type      string   `json:"type"`
	ValueType string   `json:"value_type"`
	Default   any      `json:"default"`
	Choices   []string `json:"choices"`
	Help      string   `json:"help"`
	Source    string   `json:"source"`
	Restart   bool     `json:"restart_required"`
	Multiple  bool     `json:"multiple"`
	Current   []string `json:"current"`
	PluginID  string   `json:"plugin_id,omitempty"`
	PageID    string   `json:"page_id,omitempty"`
	FieldKey  string   `json:"field_key,omitempty"`
	Action    string   `json:"action,omitempty"`
}

type PluginField struct {
	Key       string   `json:"key"`
	Label     string   `json:"label"`
	Type      string   `json:"type"`
	ValueType string   `json:"-"`
	Default   any      `json:"default"`
	Choices   []string `json:"choices"`
	Current   any      `json:"current"`
}

type PluginPage struct {
	PluginID string        `json:"plugin_id"`
	ID       string        `json:"id"`
	Title    string        `json:"title"`
	Fields   []PluginField `json:"fields"`
}

type InputData struct {
	Settings     []Setting         `json:"settings"`
	SourceFiles  []string          `json:"source_files"`
	PluginPages  []PluginPage      `json:"plugin_pages"`
	PluginErrors map[string]string `json:"plugin_errors"`
}

type Result struct {
	Action        string                                  `json:"action"`
	PluginAction  string                                  `json:"plugin_action,omitempty"`
	PluginID      string                                  `json:"plugin_id,omitempty"`
	Changes       map[string]any                          `json:"changes,omitempty"`
	PluginChanges map[string]map[string]map[string]string `json:"plugin_changes,omitempty"`
}

type mode uint8

const (
	browsing mode = iota
	searching
	editing
)

type Handler struct {
	lp        *loop.Loop
	rl        *readline.Readline
	data      InputData
	mode      mode
	query     string
	filtered  []int
	selected  int
	offset    int
	edited    map[int]any
	editIndex int
	status    string
	result    *Result
}

func (h *Handler) loadData() error {
	raw, err := io.ReadAll(os.Stdin)
	if err != nil {
		return fmt.Errorf("read settings metadata: %w", err)
	}
	if len(raw) == 0 {
		return fmt.Errorf("no settings metadata received; open this overlay from kitty")
	}
	if err := json.Unmarshal(raw, &h.data); err != nil {
		return fmt.Errorf("parse settings metadata: %w", err)
	}
	for _, page := range h.data.PluginPages {
		for _, field := range page.Fields {
			setting := Setting{
				Name: field.Label, Group: []string{"Plugins", page.PluginID, page.Title}, Type: field.Type,
				ValueType: field.Type,
				Default:   field.Default, Choices: field.Choices, Multiple: false,
				Current: []string{formatPluginValue(field.Current)}, PluginID: page.PluginID, PageID: page.ID, FieldKey: field.Key,
			}
			if field.Type == "boolean" {
				setting.Choices = []string{"true", "false"}
			}
			h.data.Settings = append(h.data.Settings, setting)
		}
	}
	if len(h.data.Settings) == 0 {
		return fmt.Errorf("kitty did not provide any settings metadata")
	}
	h.edited = make(map[int]any)
	h.refilter()
	return nil
}

func formatPluginValue(value any) string {
	if value == nil {
		return ""
	}
	return fmt.Sprint(value)
}

func (h *Handler) refilter() {
	query := strings.ToLower(strings.TrimSpace(h.query))
	h.filtered = h.filtered[:0]
	for i, setting := range h.data.Settings {
		if settingMatches(setting, query) {
			h.filtered = append(h.filtered, i)
		}
	}
	h.selected, h.offset = 0, 0
}

func settingMatches(setting Setting, query string) bool {
	if query == "" {
		return true
	}
	searchable := setting.Name + " " + strings.Join(setting.Group, " ") + " " + setting.Type + " " + setting.Help + " " + setting.Source + " " + displayValue(setting, nil)
	return strings.Contains(strings.ToLower(searchable), query)
}

func pluginActionResult(setting Setting) Result {
	return Result{Action: "plugin_action", PluginAction: setting.Action, PluginID: setting.PluginID}
}

func displayValue(setting Setting, edited any) string {
	if edited != nil {
		if value, ok := edited.(string); ok {
			return value
		}
		if value, ok := edited.([]string); ok {
			raw, _ := json.Marshal(value)
			return string(raw)
		}
	}
	if len(setting.Current) > 0 {
		if setting.Multiple {
			raw, _ := json.Marshal(setting.Current)
			return string(raw)
		}
		return setting.Current[len(setting.Current)-1]
	}
	if value, ok := setting.Default.(string); ok {
		return value + " (default)"
	}
	if value, ok := setting.Default.([]any); ok {
		raw, _ := json.Marshal(value)
		return string(raw) + " (default)"
	}
	return "(default)"
}

func fit(s string, width int) string {
	if width <= 0 || wcswidth.Stringwidth(s) <= width {
		return s
	}
	runes := []rune(s)
	for len(runes) > 0 && wcswidth.Stringwidth(string(runes))+1 > width {
		runes = runes[:len(runes)-1]
	}
	return string(runes) + "…"
}

func (h *Handler) draw() {
	sz, err := h.lp.ScreenSize()
	if err != nil {
		return
	}
	height, width := int(sz.HeightCells), int(sz.WidthCells)
	if height < 1 || width < 1 {
		return
	}
	h.lp.StartAtomicUpdate()
	defer h.lp.EndAtomicUpdate()
	h.lp.ClearScreen()
	h.lp.SetWindowTitle("Kitty Settings")
	h.lp.Println(h.lp.SprintStyled("bold fg=cyan", "Kitty Settings"))
	if h.mode != searching {
		h.lp.Printf("Search: %s", fit(h.query, width-9))
	}
	h.lp.Println()
	pluginIDs := make([]string, 0, len(h.data.PluginErrors))
	for pluginID := range h.data.PluginErrors {
		pluginIDs = append(pluginIDs, pluginID)
	}
	sort.Strings(pluginIDs)
	for _, pluginID := range pluginIDs {
		h.lp.Println(fit("Plugin error ("+pluginID+"): "+h.data.PluginErrors[pluginID], width))
	}
	if len(h.filtered) == 0 {
		h.lp.Println("No settings match this search.")
	} else {
		listHeight := max(1, height-18-len(pluginIDs))
		if h.selected < h.offset {
			h.offset = h.selected
		} else if h.selected >= h.offset+listHeight {
			h.offset = h.selected - listHeight + 1
		}
		for row := 0; row < listHeight && h.offset+row < len(h.filtered); row++ {
			idx := h.filtered[h.offset+row]
			setting := h.data.Settings[idx]
			mark := "  "
			if row+h.offset == h.selected {
				mark = h.lp.SprintStyled("fg=green bold", "> ")
			}
			value := displayValue(setting, h.edited[idx])
			line := fmt.Sprintf("%s%s  %s  %s", mark, setting.Name, value, strings.Join(setting.Group, " / "))
			h.lp.Println(fit(line, width))
		}
		if h.selected >= 0 && h.selected < len(h.filtered) {
			setting := h.data.Settings[h.filtered[h.selected]]
			h.lp.Println(h.lp.SprintStyled("dim", strings.Repeat("─", max(0, min(width, 72)))))
			h.lp.Printf("Type: %s", setting.Type)
			if setting.Multiple {
				h.lp.Printf("  Multiple values: JSON array")
			}
			if setting.Restart {
				h.lp.Printf("  Restart kitty after saving")
			}
			h.lp.Println()
			if controlHint(setting) != "" {
				h.lp.Println("Adjust: " + controlHint(setting) + "  Enter for raw value")
			}
			if setting.Source != "" {
				h.lp.Println("Source: " + fit(setting.Source, width-8))
			}
			if len(setting.Choices) > 0 {
				h.lp.Println(fit("Choices: "+strings.Join(setting.Choices, ", "), width))
			}
			if setting.Help != "" {
				h.lp.Println(fit(strings.Join(strings.Fields(setting.Help), " "), width))
			}
		}
	}
	if len(h.data.SourceFiles) > 0 {
		h.lp.Println("Config files: " + fit(strings.Join(h.data.SourceFiles, ", "), width-14))
	}
	if h.status != "" {
		h.lp.Println(h.lp.SprintStyled("fg=yellow", h.status))
	}
	if h.mode == searching || h.mode == editing {
		h.rl.RedrawNonAtomic()
	} else {
		h.lp.Println(fit("↑/↓ move   ←/→ choices   Space toggle   +/- adjust   Enter edit/run   / search   Ctrl+S save   V revert   E editor   R reload   Esc close", width))
	}
	h.lp.SetCursorVisible(h.mode != browsing)
}

func (h *Handler) initialize() (string, error) {
	h.lp.AllowLineWrapping(false)
	h.lp.SetCursorVisible(false)
	h.rl = readline.New(h.lp, readline.RlInit{DontMarkPrompts: true})
	if err := h.loadData(); err != nil {
		return "", err
	}
	h.draw()
	return "", nil
}

func (h *Handler) finish(action string) {
	h.result = &Result{Action: action}
	h.lp.Quit(0)
}

func (h *Handler) selectedSetting() (int, *Setting) {
	if h.selected < 0 || h.selected >= len(h.filtered) {
		return -1, nil
	}
	idx := h.filtered[h.selected]
	return idx, &h.data.Settings[idx]
}

func (h *Handler) beginEdit() {
	idx, setting := h.selectedSetting()
	if setting == nil {
		return
	}
	if setting.Type == "action" {
		if setting.Action == "" {
			h.status = "No action is available for this item."
			h.draw()
			return
		}
		result := pluginActionResult(*setting)
		h.result = &result
		h.lp.Quit(0)
		return
	}
	h.editIndex = idx
	h.mode = editing
	h.rl.ResetText()
	h.rl.SetText(editingValue(*setting, h.edited[idx]))
	h.rl.SetPrompt("Value: ")
	h.rl.Start()
	h.status = "Enter a value; Esc cancels. Multi-value settings use a JSON string array."
	h.draw()
}

func editingValue(setting Setting, edited any) string {
	if value, ok := edited.(string); ok {
		return value
	}
	if value, ok := edited.([]string); ok {
		raw, _ := json.Marshal(value)
		return string(raw)
	}
	if len(setting.Current) > 0 {
		if setting.Multiple {
			raw, _ := json.Marshal(setting.Current)
			return string(raw)
		}
		return setting.Current[len(setting.Current)-1]
	}
	if value, ok := setting.Default.(string); ok {
		return value
	}
	if setting.Multiple {
		if values, ok := setting.Default.([]any); ok {
			strings := make([]string, len(values))
			for i, value := range values {
				strings[i] = fmt.Sprint(value)
			}
			raw, _ := json.Marshal(strings)
			return string(raw)
		}
		if values, ok := setting.Default.([]string); ok {
			raw, _ := json.Marshal(values)
			return string(raw)
		}
	}
	return ""
}

func (h *Handler) acceptEdit() error {
	_, setting := h.selectedSettingForEdit()
	if setting == nil {
		return nil
	}
	text := h.rl.AllText()
	h.rl.End()
	value, err := decodeSettingValue(*setting, text)
	if err != nil {
		h.status = "Invalid JSON array: " + err.Error()
		h.mode = editing
		h.rl.Start()
		h.draw()
		return nil
	}
	h.edited[h.editIndex] = value
	h.mode = browsing
	h.status = "Value changed in this session; Ctrl+S writes and reloads kitty.conf."
	h.draw()
	return nil
}

func (h *Handler) selectedSettingForEdit() (int, *Setting) {
	if h.editIndex < 0 || h.editIndex >= len(h.data.Settings) {
		return -1, nil
	}
	return h.editIndex, &h.data.Settings[h.editIndex]
}

func (h *Handler) cycleChoice(direction int) {
	idx, setting := h.selectedSetting()
	if setting == nil || setting.Multiple || len(setting.Choices) == 0 {
		return
	}
	h.edited[idx] = nextChoice(setting.Choices, choiceValue(*setting, h.edited[idx]), direction)
	h.status = "Selected choice; Ctrl+S saves and reloads kitty.conf."
	h.draw()
}

func controlHint(setting Setting) string {
	if setting.Multiple {
		return ""
	}
	if len(setting.Choices) > 0 {
		return "←/→ cycle choices"
	}
	switch setting.ValueType {
	case "to_bool", "boolean", "bool":
		return "Space toggle"
	case "int", "positive_int", "float", "positive_float", "to_font_size":
		return "+/- adjust numeric value"
	}
	return ""
}

func settingValue(setting Setting, edited any) string {
	if value, ok := edited.(string); ok {
		return value
	}
	if len(setting.Current) > 0 {
		return setting.Current[len(setting.Current)-1]
	}
	if value, ok := setting.Default.(string); ok {
		return value
	}
	return ""
}

func toggleBoolean(current string) string {
	if strings.EqualFold(current, "yes") || strings.EqualFold(current, "y") || strings.EqualFold(current, "true") {
		return "no"
	}
	return "yes"
}

func adjustNumber(current, valueType string, direction int) (string, bool) {
	if valueType == "int" || valueType == "positive_int" {
		value, err := strconv.Atoi(current)
		if err != nil {
			return "", false
		}
		value += direction
		if valueType == "positive_int" && value < 0 {
			value = 0
		}
		return strconv.Itoa(value), true
	}
	if valueType == "float" || valueType == "positive_float" || valueType == "to_font_size" {
		value, err := strconv.ParseFloat(current, 64)
		if err != nil || math.IsNaN(value) || math.IsInf(value, 0) {
			return "", false
		}
		value += float64(direction) * 0.1
		if valueType == "positive_float" && value < 0 {
			value = 0
		} else if valueType == "to_font_size" && value < 4 {
			value = 4
		}
		return strconv.FormatFloat(value, 'f', -1, 64), true
	}
	return "", false
}

func (h *Handler) adjustSelected(direction int) {
	idx, setting := h.selectedSetting()
	if setting == nil || setting.Multiple {
		return
	}
	if setting.ValueType == "to_bool" || setting.ValueType == "boolean" || setting.ValueType == "bool" {
		h.edited[idx] = toggleBoolean(settingValue(*setting, h.edited[idx]))
		h.status = "Selected boolean value; Ctrl+S saves and reloads kitty.conf."
		h.draw()
		return
	}
	if value, ok := adjustNumber(settingValue(*setting, h.edited[idx]), setting.ValueType, direction); ok {
		h.edited[idx] = value
		h.status = "Adjusted value; Ctrl+S saves and reloads kitty.conf."
		h.draw()
	}
}

func choiceValue(setting Setting, edited any) string {
	if value, ok := edited.(string); ok {
		return value
	}
	if len(setting.Current) > 0 {
		return setting.Current[len(setting.Current)-1]
	}
	value, _ := setting.Default.(string)
	return value
}

func nextChoice(choices []string, current string, direction int) string {
	choice := -1
	for i, value := range choices {
		if value == current {
			choice = i
			break
		}
	}
	choice = (choice + direction + len(choices)) % len(choices)
	return choices[choice]
}

func decodeSettingValue(setting Setting, text string) (any, error) {
	if !setting.Multiple {
		return text, nil
	}
	var values []string
	if err := json.Unmarshal([]byte(text), &values); err != nil {
		return nil, err
	}
	if values == nil {
		return nil, fmt.Errorf("expected a JSON array of strings")
	}
	return values, nil
}

func (h *Handler) onText(text string, fromKeyEvent, bracketedPaste bool) error {
	if h.mode == searching {
		if err := h.rl.OnText(text, fromKeyEvent, bracketedPaste); err != nil {
			return err
		}
		h.query = h.rl.AllText()
		h.refilter()
		h.draw()
	} else if h.mode == editing {
		if err := h.rl.OnText(text, fromKeyEvent, bracketedPaste); err != nil {
			return err
		}
		h.draw()
	}
	return nil
}

func (h *Handler) onKeyEvent(ev *loop.KeyEvent) error {
	if h.mode == editing {
		if ev.MatchesPressOrRepeat("esc") {
			ev.Handled = true
			h.rl.End()
			h.mode, h.status = browsing, "Edit canceled."
			h.draw()
			return nil
		}
		if ev.MatchesPressOrRepeat("enter") || ev.MatchesPressOrRepeat("kp_enter") {
			ev.Handled = true
			return h.acceptEdit()
		}
		if err := h.rl.OnKeyEvent(ev); err != nil && err != readline.ErrAcceptInput {
			return err
		}
		h.draw()
		return nil
	}
	if h.mode == searching {
		if ev.MatchesPressOrRepeat("esc") {
			ev.Handled = true
			h.rl.End()
			h.mode, h.query = browsing, ""
			h.rl.SetPrompt("")
			h.refilter()
			h.draw()
			return nil
		}
		if ev.MatchesPressOrRepeat("enter") || ev.MatchesPressOrRepeat("kp_enter") {
			ev.Handled = true
			h.query = h.rl.AllText()
			h.rl.End()
			h.mode = browsing
			h.rl.SetPrompt("")
			h.draw()
			return nil
		}
		if err := h.rl.OnKeyEvent(ev); err != nil && err != readline.ErrAcceptInput {
			return err
		}
		h.query = h.rl.AllText()
		h.refilter()
		h.draw()
		return nil
	}

	switch {
	case ev.MatchesPressOrRepeat("ctrl+c"):
		ev.Handled = true
		h.lp.Quit(0)
	case ev.MatchesPressOrRepeat("esc"):
		ev.Handled = true
		if len(h.edited) > 0 {
			h.status = "Unsaved changes are discarded with Ctrl+C, saved with Ctrl+S."
			h.draw()
		} else {
			h.lp.Quit(0)
		}
	case ev.MatchesPressOrRepeat("up"), ev.MatchesPressOrRepeat("ctrl+k"):
		ev.Handled = true
		h.selected = max(0, h.selected-1)
		h.status = ""
		h.draw()
	case ev.MatchesPressOrRepeat("down"), ev.MatchesPressOrRepeat("ctrl+j"):
		ev.Handled = true
		h.selected = min(max(0, len(h.filtered)-1), h.selected+1)
		h.status = ""
		h.draw()
	case ev.MatchesPressOrRepeat("page_up"):
		ev.Handled = true
		h.selected = max(0, h.selected-10)
		h.draw()
	case ev.MatchesPressOrRepeat("page_down"):
		ev.Handled = true
		h.selected = min(max(0, len(h.filtered)-1), h.selected+10)
		h.draw()
	case ev.MatchesPressOrRepeat("left"), ev.MatchesPressOrRepeat("h"):
		ev.Handled = true
		h.cycleChoice(-1)
	case ev.MatchesPressOrRepeat("right"), ev.MatchesPressOrRepeat("l"):
		ev.Handled = true
		h.cycleChoice(1)
	case ev.MatchesPressOrRepeat("space"):
		ev.Handled = true
		h.adjustSelected(1)
	case ev.MatchesPressOrRepeat("+"):
		ev.Handled = true
		h.adjustSelected(1)
	case ev.MatchesPressOrRepeat("-"):
		ev.Handled = true
		h.adjustSelected(-1)
	case ev.MatchesPressOrRepeat("enter"), ev.MatchesPressOrRepeat("kp_enter"):
		ev.Handled = true
		h.beginEdit()
	case ev.MatchesPressOrRepeat("/"):
		ev.Handled = true
		h.mode = searching
		h.rl.ResetText()
		h.rl.SetText(h.query)
		h.rl.SetPrompt("Search: ")
		h.rl.Start()
		h.draw()
	case ev.MatchesPressOrRepeat("ctrl+s"):
		ev.Handled = true
		changes := make(map[string]any, len(h.edited))
		pluginChanges := make(map[string]map[string]map[string]string)
		for idx, value := range h.edited {
			setting := h.data.Settings[idx]
			if setting.PluginID != "" {
				value, ok := value.(string)
				if !ok {
					h.status = "Invalid plugin setting value."
					h.draw()
					return nil
				}
				if pluginChanges[setting.PluginID] == nil {
					pluginChanges[setting.PluginID] = make(map[string]map[string]string)
				}
				if pluginChanges[setting.PluginID][setting.PageID] == nil {
					pluginChanges[setting.PluginID][setting.PageID] = make(map[string]string)
				}
				pluginChanges[setting.PluginID][setting.PageID][setting.FieldKey] = value
			} else {
				changes[setting.Name] = value
			}
		}
		if len(changes) == 0 && len(pluginChanges) == 0 {
			h.status = "No settings changed."
			h.draw()
		} else {
			h.result = &Result{Action: "save", Changes: changes, PluginChanges: pluginChanges}
			h.lp.Quit(0)
		}
	case ev.MatchesPressOrRepeat("e"):
		ev.Handled = true
		if len(h.edited) > 0 {
			h.status = "Save or discard the in-memory changes before opening the text editor."
			h.draw()
		} else {
			h.finish("edit")
		}
	case ev.MatchesPressOrRepeat("r"):
		ev.Handled = true
		if len(h.edited) > 0 {
			h.status = "Save or discard the in-memory changes before reloading."
			h.draw()
		} else {
			h.finish("reload")
		}
	case ev.MatchesPressOrRepeat("v"):
		ev.Handled = true
		if len(h.edited) > 0 {
			h.status = "Save or discard the in-memory changes before reverting."
			h.draw()
		} else {
			h.finish("revert")
		}
	}
	return nil
}

func main(_ *cli.Command, _ *Options, _ []string) (rc int, err error) {
	lp, err := loop.New()
	if err != nil {
		return 1, err
	}
	h := &Handler{lp: lp}
	lp.OnInitialize = h.initialize
	lp.OnFinalize = func() string {
		if h.mode != browsing {
			h.rl.End()
		}
		lp.SetCursorVisible(true)
		return ""
	}
	lp.OnResize = func(_, _ loop.ScreenSize) error { h.draw(); return nil }
	lp.OnKeyEvent = h.onKeyEvent
	lp.OnText = h.onText
	output := tui.KittenOutputSerializer()
	if err = lp.Run(); err != nil {
		return 1, err
	}
	if lp.DeathSignalName() != "" {
		return 1, fmt.Errorf("settings overlay terminated by signal: %s", lp.DeathSignalName())
	}
	if h.result != nil {
		encoded, err := output(h.result)
		if err != nil {
			return 1, err
		}
		fmt.Println(encoded)
	}
	return lp.ExitCode(), nil
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
