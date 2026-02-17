import os
import re
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Check for potential SQL injection vulnerabilities in the codebase'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('🔍 Checking for SQL injection vulnerabilities...\n'))

        vulnerabilities_found = 0

        # Check for raw SQL usage
        self.stdout.write('Checking for raw SQL usage...')
        raw_sql_files = self._find_raw_sql_usage()
        if raw_sql_files:
            self.stdout.write(self.style.ERROR(f'❌ Found {len(raw_sql_files)} files with raw SQL usage:'))
            for file_path in raw_sql_files:
                self.stdout.write(f'  - {file_path}')
            vulnerabilities_found += len(raw_sql_files)
        else:
            self.stdout.write(self.style.SUCCESS('✅ No raw SQL usage found'))

        # Check for unsafe string formatting in queries
        self.stdout.write('\nChecking for unsafe string formatting...')
        unsafe_formatting = self._find_unsafe_string_formatting()
        if unsafe_formatting:
            self.stdout.write(self.style.ERROR(f'❌ Found {len(unsafe_formatting)} instances of unsafe string formatting:'))
            for file_path, line_num, line in unsafe_formatting:
                self.stdout.write(f'  - {file_path}:{line_num} - {line.strip()}')
            vulnerabilities_found += len(unsafe_formatting)
        else:
            self.stdout.write(self.style.SUCCESS('✅ No unsafe string formatting found'))

        # Check for missing input validation
        self.stdout.write('\nChecking for input validation...')
        missing_validation = self._check_input_validation()
        if missing_validation:
            self.stdout.write(self.style.WARNING(f'⚠️  Found {len(missing_validation)} areas that could benefit from additional validation:'))
            for item in missing_validation:
                self.stdout.write(f'  - {item}')
        else:
            self.stdout.write(self.style.SUCCESS('✅ Input validation looks good'))

        # Check security settings
        self.stdout.write('\nChecking security settings...')
        security_issues = self._check_security_settings()
        if security_issues:
            self.stdout.write(self.style.WARNING(f'⚠️  Found {len(security_issues)} security configuration issues:'))
            for issue in security_issues:
                self.stdout.write(f'  - {issue}')
        else:
            self.stdout.write(self.style.SUCCESS('✅ Security settings are properly configured'))

        # Summary
        self.stdout.write('\n' + '='*50)
        if vulnerabilities_found == 0:
            self.stdout.write(self.style.SUCCESS('🎉 No SQL injection vulnerabilities found!'))
            self.stdout.write(self.style.SUCCESS('Your Django application appears to be secure against SQL injection.'))
        else:
            self.stdout.write(self.style.ERROR(f'🚨 Found {vulnerabilities_found} potential SQL injection vulnerabilities!'))
            self.stdout.write(self.style.ERROR('Please review and fix these issues immediately.'))

    def _find_raw_sql_usage(self):
        """Find files that use raw SQL queries"""
        raw_sql_patterns = [
            r'\.raw\(',
            r'cursor\.execute',
            r'connection\.cursor',
            r'select.*from.*where.*%s',
            r'insert.*into.*values.*%s',
        ]

        vulnerable_files = []
        for root, dirs, files in os.walk(settings.BASE_DIR):
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            for pattern in raw_sql_patterns:
                                if re.search(pattern, content, re.IGNORECASE):
                                    vulnerable_files.append(file_path)
                                    break
                    except:
                        pass
        return list(set(vulnerable_files))

    def _find_unsafe_string_formatting(self):
        """Find unsafe string formatting in database queries"""
        unsafe_patterns = [
            r'filter\(.*%.*\)',
            r'exclude\(.*%.*\)',
            r'Q\(.*%.*\)',
        ]

        vulnerable_instances = []
        for root, dirs, files in os.walk(settings.BASE_DIR):
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            lines = f.readlines()
                            for line_num, line in enumerate(lines, 1):
                                for pattern in unsafe_patterns:
                                    if re.search(pattern, line):
                                        vulnerable_instances.append((file_path, line_num, line))
                    except:
                        pass
        return vulnerable_instances

    def _check_input_validation(self):
        """Check for missing input validation"""
        issues = []

        # Check if serializers have validation
        serializer_files = []
        for root, dirs, files in os.walk(settings.BASE_DIR):
            for file in files:
                if 'serializer' in file.lower() and file.endswith('.py'):
                    serializer_files.append(os.path.join(root, file))

        for file_path in serializer_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if 'validate_' not in content:
                        issues.append(f'{file_path}: No custom validation methods found')
            except:
                pass

        return issues

    def _check_security_settings(self):
        """Check Django security settings"""
        issues = []

        # Check if DEBUG is True (should be False in production)
        if getattr(settings, 'DEBUG', False):
            issues.append('DEBUG is set to True - should be False in production')

        # Check if SECRET_KEY is properly set
        secret_key = getattr(settings, 'SECRET_KEY', '')
        if not secret_key or secret_key == 'your-secret-key-here':
            issues.append('SECRET_KEY is not properly configured')

        # Check CORS settings
        if getattr(settings, 'CORS_ALLOW_ALL_ORIGINS', False):
            issues.append('CORS_ALLOW_ALL_ORIGINS is True - consider restricting origins')

        return issues