// License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

package settings

import (
	"encoding/json"
	"reflect"
	"testing"
)

func TestDecodeSettingValue(t *testing.T) {
	value, err := decodeSettingValue(Setting{}, "12.5")
	if err != nil || value != "12.5" {
		t.Fatalf("scalar value = %#v, %v", value, err)
	}
	value, err = decodeSettingValue(Setting{Multiple: true}, `["one","two words"]`)
	if err != nil || !reflect.DeepEqual(value, []string{"one", "two words"}) {
		t.Fatalf("multi-value = %#v, %v", value, err)
	}
	for _, text := range []string{`"one"`, `[1]`, `null`} {
		if _, err := decodeSettingValue(Setting{Multiple: true}, text); err == nil {
			t.Errorf("accepted invalid multi-value input %q", text)
		}
	}
}

func TestNextChoice(t *testing.T) {
	choices := []string{"one", "two", "three"}
	for _, test := range []struct {
		current   string
		direction int
		want      string
	}{
		{"one", -1, "three"},
		{"two", 1, "three"},
		{"unknown", 1, "one"},
	} {
		if got := nextChoice(choices, test.current, test.direction); got != test.want {
			t.Errorf("nextChoice(%q, %d) = %q, want %q", test.current, test.direction, got, test.want)
		}
	}
}

func TestEditingValueUsesMultiValueDefaults(t *testing.T) {
	setting := Setting{Multiple: true, Default: []any{"one", "two words"}}
	if got := editingValue(setting, nil); got != `["one","two words"]` {
		t.Fatalf("editingValue with defaults = %q", got)
	}
	setting.Current = []string{"custom value"}
	if got := editingValue(setting, nil); got != `["custom value"]` {
		t.Fatalf("editingValue with current values = %q", got)
	}
	if got := editingValue(setting, []string{"edited"}); got != `["edited"]` {
		t.Fatalf("editingValue with edited values = %q", got)
	}
}

func TestSettingSearchIncludesCatalogSourceAndVersion(t *testing.T) {
	setting := Setting{Name: "Catalog plugin: Demo", Group: []string{"Plugins"}, Type: "action", Source: "https://example.com/demo", Current: []string{"1.2.3"}}
	for _, query := range []string{"demo", "example.com", "1.2.3"} {
		if !settingMatches(setting, query) {
			t.Errorf("settingMatches did not find %q", query)
		}
	}
	if settingMatches(setting, "not-present") {
		t.Fatal("settingMatches accepted a missing query")
	}
}

func TestPluginActionResultUsesStableFields(t *testing.T) {
	got := pluginActionResult(Setting{Action: "install_catalog_plugin", PluginID: "demo-plugin"})
	if got.Action != "plugin_action" || got.PluginAction != "install_catalog_plugin" || got.PluginID != "demo-plugin" {
		t.Fatalf("plugin action result = %#v", got)
	}
	raw, err := json.Marshal(got)
	if err != nil {
		t.Fatal(err)
	}
	want := `{"action":"plugin_action","plugin_action":"install_catalog_plugin","plugin_id":"demo-plugin"}`
	if string(raw) != want {
		t.Fatalf("serialized action result = %s, want %s", raw, want)
	}
}

func TestTypedAdjustments(t *testing.T) {
	if got := toggleBoolean("true"); got != "no" {
		t.Fatalf("toggleBoolean(true) = %q", got)
	}
	if got := toggleBoolean("no"); got != "yes" {
		t.Fatalf("toggleBoolean(no) = %q", got)
	}
	for _, test := range []struct {
		current, kind string
		direction     int
		want          string
	}{
		{"4", "int", 1, "5"},
		{"0", "positive_int", -1, "0"},
		{"0.5", "float", -1, "0.4"},
		{"0.1", "positive_float", -1, "0"},
	} {
		got, ok := adjustNumber(test.current, test.kind, test.direction)
		if !ok || got != test.want {
			t.Errorf("adjustNumber(%q, %q, %d) = %q, %v; want %q", test.current, test.kind, test.direction, got, ok, test.want)
		}
	}
	if _, ok := adjustNumber("not a number", "float", 1); ok {
		t.Fatal("accepted invalid numeric value")
	}
}
