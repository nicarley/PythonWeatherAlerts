import SwiftUI

struct LocationEditorView: View {
    @Environment(\.dismiss) private var dismiss
    @State var draft: LocationDraft
    @State private var isSaving = false

    let onSave: (LocationDraft) async -> Void

    var body: some View {
        NavigationStack {
            Form {
                Section("Location") {
                    TextField("Name", text: $draft.name)
                    TextField("ZIP, City/State, Station, or lat,lon", text: $draft.query)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }

                Section("Alert Rules") {
                    Picker("Minimum Severity", selection: $draft.rules.minimumSeverity) {
                        ForEach(AlertSeverity.allCases) { severity in
                            Text(severity.displayName).tag(severity)
                        }
                    }

                    ForEach([AlertKind.warning, AlertKind.watch, AlertKind.advisory]) { kind in
                        Toggle(kind.displayName, isOn: enabledKindBinding(for: kind))
                    }
                }

                Section("Examples") {
                    Text("62881")
                    Text("Mount Vernon, IL")
                    Text("KSTL")
                    Text("38.6317,-88.9416")
                }
                .foregroundStyle(.secondary)
            }
            .navigationTitle(draft.existingLocation == nil ? "Add Location" : "Edit Location")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") {
                        dismiss()
                    }
                }

                ToolbarItem(placement: .confirmationAction) {
                    Button(isSaving ? "Saving..." : "Save") {
                        Task {
                            isSaving = true
                            await onSave(draft)
                            isSaving = false
                        }
                    }
                    .disabled(
                        isSaving ||
                        draft.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ||
                        draft.query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ||
                        draft.rules.enabledKinds.isEmpty
                    )
                }
            }
        }
    }

    private func enabledKindBinding(for kind: AlertKind) -> Binding<Bool> {
        Binding(
            get: { draft.rules.enabledKinds.contains(kind) },
            set: { isEnabled in
                if isEnabled {
                    if !draft.rules.enabledKinds.contains(kind) {
                        draft.rules.enabledKinds.append(kind)
                    }
                } else {
                    draft.rules.enabledKinds.removeAll { $0 == kind }
                }
            }
        )
    }
}
