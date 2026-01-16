function confirmRoleChange() {
            return confirm(
                '⚠️ FINAL WARNING ⚠️\n\n' +
                'This will permanently delete ALL existing profile data and dependent records.\n' +
                'This action cannot be undone.\n\n' +
                'Are you absolutely sure you want to proceed?'
            );
        }