/**
 * Departman tanımları (server/teams.py DEPARTMENTS ile aynı sıra ve roller).
 * Ofis görünümü senkron bir yerleşim ister; Petek görünümü ise sunucudan /api/teams ile çeker.
 */
export interface DepartmentDef {
  id: 'ANALIZ' | 'YAZILIM' | 'TEST' | 'DESTEK';
  label: string;
  roles: string[];
  color: 'ac' | 'ok' | 'warn' | 'info';
}

export const DEPARTMENTS: DepartmentDef[] = [
  { id: 'ANALIZ', label: 'Analiz Ekibi', roles: ['PM', 'PO', 'ARCHITECT'], color: 'ac' },
  { id: 'YAZILIM', label: 'Yazılım Ekibi', roles: ['BACKEND_DEV', 'FRONTEND_DEV', 'DESIGNER', 'SCM', 'DEVOPS'], color: 'ok' },
  { id: 'TEST', label: 'Test Ekibi', roles: ['QA', 'E2E_TESTER'], color: 'warn' },
  { id: 'DESTEK', label: 'Destek Ekibi', roles: ['REPORTER', 'DOCUMENTOR'], color: 'info' },
];

export const FALLBACK_DEPARTMENT: DepartmentDef['id'] = 'YAZILIM';

export function departmentOf(roleOrId: string): DepartmentDef {
  const key = roleOrId.toUpperCase();
  return DEPARTMENTS.find(d => d.roles.includes(key)) || DEPARTMENTS.find(d => d.id === FALLBACK_DEPARTMENT)!;
}
