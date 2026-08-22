import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router';

import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table';

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import {
  LucideDot,
  LucideEraser,
  LucidePlus,
  LucideSearch,
  LucideTrash2,
} from 'lucide-react';

import Spotlight from '@/components/spotlight';
import { TableEmpty } from '@/components/table-skeleton';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RAGFlowPagination } from '@/components/ui/ragflow-pagination';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';

import {
  createCacheL2Entry,
  deleteCacheL1Entries,
  deleteCacheL2Entries,
  getCacheStats,
  getCacheTenantDialogs,
  getCacheTenants,
  invalidateCacheL1Dialog,
  listCacheL1Dialogs,
  listCacheL1Entries,
  listCacheL2Entries,
  updateCacheL2Entry,
} from '@/services/admin-service';

const l2ColumnHelper = createColumnHelper<AdminService.CacheL2Entry>();
const l1ColumnHelper = createColumnHelper<AdminService.CacheL1Entry>();

function formatTimestamp(ts: number) {
  if (!ts) return '-';
  const d = new Date(ts * 1000);
  return d.toLocaleString();
}

function formatTTL(seconds: number) {
  if (seconds >= 86400) return `${Math.round(seconds / 86400)}d`;
  if (seconds >= 3600) return `${Math.round(seconds / 3600)}h`;
  return `${seconds}s`;
}

function truncate(str: string, maxLen = 80) {
  if (!str) return '-';
  return str.length > maxLen ? str.slice(0, maxLen) + '...' : str;
}

function CacheManagement() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();

  const [activeTab, setActiveTab] = useState('l1');

  // L2 State
  const [selectedTenantId, setSelectedTenantId] = useState<string>('');
  const [selectedDialogId, setSelectedDialogId] = useState<string>('');
  const [questionSearch, setQuestionSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedRows, setSelectedRows] = useState<string[]>([]);

  // L1 State
  const [l1DialogId, setL1DialogId] = useState<string>('');
  const [l1Page, setL1Page] = useState(1);
  const [l1PageSize, setL1PageSize] = useState(20);
  const [l1SelectedRows, setL1SelectedRows] = useState<string[]>([]);
  const [l1DeleteModalOpen, setL1DeleteModalOpen] = useState(false);

  // L2 Modals
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editEntry, setEditEntry] = useState<AdminService.CacheL2Entry | null>(
    null,
  );
  const [editAnswer, setEditAnswer] = useState('');
  const [editTTL, setEditTTL] = useState('5184000');

  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [createQuestion, setCreateQuestion] = useState('');
  const [createAnswer, setCreateAnswer] = useState('');
  const [createTTL, setCreateTTL] = useState('5184000');
  const [createDialogId, setCreateDialogId] = useState('');

  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [invalidateModalOpen, setInvalidateModalOpen] = useState(false);

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(questionSearch), 300);
    return () => clearTimeout(timer);
  }, [questionSearch]);

  // Reset page when filters change
  useEffect(() => {
    setPage(1);
  }, [selectedTenantId, selectedDialogId, debouncedSearch]);

  useEffect(() => {
    setL1Page(1);
  }, [l1DialogId]);

  // Read dialog_id from URL params
  useEffect(() => {
    const dialogIdParam = searchParams.get('dialog_id');
    if (dialogIdParam) {
      setSelectedDialogId(dialogIdParam);
    }
  }, [searchParams]);

  // ─── Queries ──────────────────────────────────────────────

  const { data: stats } = useQuery({
    queryKey: ['admin/cacheStats'],
    queryFn: async () => (await getCacheStats())?.data?.data,
    refetchInterval: 30000,
  });

  // L1 queries
  const { data: l1Dialogs } = useQuery({
    queryKey: ['admin/cacheL1Dialogs'],
    queryFn: async () => (await listCacheL1Dialogs())?.data?.data,
  });

  const { data: l1EntriesResponse, isLoading: isLoadingL1 } = useQuery({
    queryKey: ['admin/cacheL1Entries', l1DialogId, l1Page, l1PageSize],
    queryFn: async () =>
      (
        await listCacheL1Entries({
          dialogId: l1DialogId || undefined,
          page: l1Page,
          pageSize: l1PageSize,
        })
      )?.data?.data,
    placeholderData: keepPreviousData,
  });

  const l1Entries = l1EntriesResponse?.entries ?? [];
  const l1Total = l1EntriesResponse?.total ?? 0;

  // L2 queries
  const { data: tenants } = useQuery({
    queryKey: ['admin/cacheTenants'],
    queryFn: async () => (await getCacheTenants())?.data?.data,
  });

  const { data: dialogs } = useQuery({
    queryKey: ['admin/cacheDialogs', selectedTenantId],
    queryFn: async () =>
      (await getCacheTenantDialogs(selectedTenantId))?.data?.data,
    enabled: !!selectedTenantId,
  });

  // Auto-select first tenant if URL has dialog_id
  useEffect(() => {
    if (
      selectedDialogId &&
      !selectedTenantId &&
      tenants &&
      tenants.length > 0
    ) {
      setSelectedTenantId(tenants[0].tenant_id);
    }
  }, [selectedDialogId, selectedTenantId, tenants]);

  const { data: entriesResponse, isLoading: isLoadingEntries } = useQuery({
    queryKey: [
      'admin/cacheL2Entries',
      selectedTenantId,
      selectedDialogId,
      debouncedSearch,
      page,
      pageSize,
    ],
    queryFn: async () =>
      (
        await listCacheL2Entries({
          tenantId: selectedTenantId,
          dialogId: selectedDialogId || undefined,
          questionSearch: debouncedSearch || undefined,
          page,
          pageSize,
        })
      )?.data?.data,
    enabled: !!selectedTenantId,
    placeholderData: keepPreviousData,
  });

  const entries = entriesResponse?.entries ?? [];
  const totalEntries = entriesResponse?.total ?? 0;

  // ─── Mutations ────────────────────────────────────────────

  const updateMutation = useMutation({
    mutationFn: async () => {
      if (!editEntry || !selectedTenantId) return;
      await updateCacheL2Entry(selectedTenantId, editEntry.id, {
        answer_json: editAnswer,
        ttl: parseInt(editTTL, 10),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin/cacheL2Entries'] });
      queryClient.invalidateQueries({ queryKey: ['admin/cacheStats'] });
      setEditModalOpen(false);
      setEditEntry(null);
    },
  });

  const createMutation = useMutation({
    mutationFn: async () => {
      if (!selectedTenantId) return;
      await createCacheL2Entry({
        tenantId: selectedTenantId,
        dialogId: createDialogId || selectedDialogId,
        questionText: createQuestion,
        answer: createAnswer,
        ttl: parseInt(createTTL, 10),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin/cacheL2Entries'] });
      queryClient.invalidateQueries({ queryKey: ['admin/cacheStats'] });
      setCreateModalOpen(false);
      setCreateQuestion('');
      setCreateAnswer('');
      setCreateTTL('5184000');
      setCreateDialogId('');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async () => {
      if (!selectedTenantId || selectedRows.length === 0) return;
      await deleteCacheL2Entries(selectedTenantId, selectedRows);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin/cacheL2Entries'] });
      queryClient.invalidateQueries({ queryKey: ['admin/cacheStats'] });
      setDeleteModalOpen(false);
      setSelectedRows([]);
    },
  });

  const l1DeleteMutation = useMutation({
    mutationFn: async () => {
      if (l1SelectedRows.length === 0) return;
      await deleteCacheL1Entries(l1SelectedRows);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin/cacheL1Entries'] });
      queryClient.invalidateQueries({ queryKey: ['admin/cacheL1Dialogs'] });
      queryClient.invalidateQueries({ queryKey: ['admin/cacheStats'] });
      setL1DeleteModalOpen(false);
      setL1SelectedRows([]);
    },
  });

  const invalidateL1Mutation = useMutation({
    mutationFn: async () => {
      if (!selectedDialogId) return;
      await invalidateCacheL1Dialog(selectedDialogId);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin/cacheStats'] });
      queryClient.invalidateQueries({ queryKey: ['admin/cacheL1Entries'] });
      queryClient.invalidateQueries({ queryKey: ['admin/cacheL1Dialogs'] });
      setInvalidateModalOpen(false);
    },
  });

  // ─── Callbacks ────────────────────────────────────────────

  const handleEditClick = useCallback((entry: AdminService.CacheL2Entry) => {
    setEditEntry(entry);
    setEditAnswer(entry.answer_json);
    setEditTTL(String(entry.ttl));
    setEditModalOpen(true);
  }, []);

  const toggleRowSelection = useCallback((id: string) => {
    setSelectedRows((prev) =>
      prev.includes(id) ? prev.filter((r) => r !== id) : [...prev, id],
    );
  }, []);

  const toggleAllRows = useCallback(() => {
    setSelectedRows((prev) =>
      prev.length === entries.length ? [] : entries.map((e) => e.id),
    );
  }, [entries]);

  const toggleL1RowSelection = useCallback((key: string) => {
    setL1SelectedRows((prev) =>
      prev.includes(key) ? prev.filter((r) => r !== key) : [...prev, key],
    );
  }, []);

  const toggleAllL1Rows = useCallback(() => {
    setL1SelectedRows((prev) =>
      prev.length === l1Entries.length ? [] : l1Entries.map((e) => e.key),
    );
  }, [l1Entries]);

  // ─── L1 Table columns ────────────────────────────────────

  const l1ColumnDefs = useMemo(
    () => [
      l1ColumnHelper.display({
        id: 'select',
        header: () => (
          <input
            type="checkbox"
            checked={
              l1SelectedRows.length > 0 &&
              l1SelectedRows.length === l1Entries.length
            }
            onChange={toggleAllL1Rows}
            className="rounded"
          />
        ),
        cell: ({ row }) => (
          <input
            type="checkbox"
            checked={l1SelectedRows.includes(row.original.key)}
            onChange={() => toggleL1RowSelection(row.original.key)}
            className="rounded"
          />
        ),
      }),
      l1ColumnHelper.accessor('question_text', {
        header: t('admin.question'),
        cell: ({ cell }) => {
          const val = cell.getValue();
          return (
            <span title={val}>
              {val ? truncate(val, 60) : t('admin.noQuestionStored')}
            </span>
          );
        },
      }),
      l1ColumnHelper.accessor('answer', {
        header: t('admin.answer'),
        cell: ({ cell }) => (
          <span title={cell.getValue()}>{truncate(cell.getValue(), 60)}</span>
        ),
      }),
      l1ColumnHelper.accessor('dialog_name', {
        header: t('admin.dialog'),
        cell: ({ cell, row }) => cell.getValue() || row.original.dialog_id,
      }),
      l1ColumnHelper.accessor('cached_at', {
        header: t('admin.cachedAt'),
        cell: ({ cell }) => formatTimestamp(cell.getValue()),
      }),
      l1ColumnHelper.accessor('ttl_remaining', {
        header: t('admin.ttl'),
        cell: ({ cell }) => formatTTL(cell.getValue()),
      }),
      l1ColumnHelper.display({
        id: 'actions',
        header: t('admin.actions'),
        cell: ({ row }) => (
          <div className="opacity-0 group-hover/row:opacity-100 group-focus-within/row:opacity-100 transition-opacity">
            <Button
              variant="danger"
              size="icon"
              className="border-0 size-8"
              onClick={() => {
                setL1SelectedRows([row.original.key]);
                setL1DeleteModalOpen(true);
              }}
            >
              <LucideTrash2 className="size-4" />
            </Button>
          </div>
        ),
      }),
    ],
    [t, l1SelectedRows, l1Entries, toggleAllL1Rows, toggleL1RowSelection],
  );

  const l1Table = useReactTable({
    data: l1Entries,
    columns: l1ColumnDefs,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: Math.ceil(l1Total / l1PageSize),
  });

  // ─── L2 Table columns ────────────────────────────────────

  const l2ColumnDefs = useMemo(
    () => [
      l2ColumnHelper.display({
        id: 'select',
        header: () => (
          <input
            type="checkbox"
            checked={
              selectedRows.length > 0 && selectedRows.length === entries.length
            }
            onChange={toggleAllRows}
            className="rounded"
          />
        ),
        cell: ({ row }) => (
          <input
            type="checkbox"
            checked={selectedRows.includes(row.original.id)}
            onChange={() => toggleRowSelection(row.original.id)}
            className="rounded"
          />
        ),
      }),
      l2ColumnHelper.accessor('question_text', {
        header: t('admin.question'),
        cell: ({ cell }) => (
          <span title={cell.getValue()}>{truncate(cell.getValue(), 60)}</span>
        ),
      }),
      l2ColumnHelper.accessor('answer_json', {
        header: t('admin.answer'),
        cell: ({ cell }) => (
          <span title={cell.getValue()}>{truncate(cell.getValue(), 60)}</span>
        ),
      }),
      l2ColumnHelper.accessor('dialog_name', {
        header: t('admin.dialog'),
        cell: ({ cell, row }) => cell.getValue() || row.original.dialog_id,
      }),
      l2ColumnHelper.accessor('cached_at', {
        header: t('admin.cachedAt'),
        cell: ({ cell }) => formatTimestamp(cell.getValue()),
      }),
      l2ColumnHelper.accessor('ttl', {
        header: t('admin.ttl'),
        cell: ({ cell }) => formatTTL(cell.getValue()),
      }),
      l2ColumnHelper.display({
        id: 'actions',
        header: t('admin.actions'),
        cell: ({ row }) => (
          <div className="opacity-0 group-hover/row:opacity-100 group-focus-within/row:opacity-100 transition-opacity flex gap-1">
            <Button
              variant="transparent"
              size="icon"
              className="border-0 size-8"
              onClick={() => handleEditClick(row.original)}
            >
              ✏️
            </Button>
            <Button
              variant="danger"
              size="icon"
              className="border-0 size-8"
              onClick={() => {
                setSelectedRows([row.original.id]);
                setDeleteModalOpen(true);
              }}
            >
              <LucideTrash2 className="size-4" />
            </Button>
          </div>
        ),
      }),
    ],
    [
      t,
      selectedRows,
      entries,
      toggleAllRows,
      toggleRowSelection,
      handleEditClick,
    ],
  );

  const l2Table = useReactTable({
    data: entries,
    columns: l2ColumnDefs,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: Math.ceil(totalEntries / pageSize),
  });

  // ─── Render helpers ───────────────────────────────────────

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const renderTable = (
    tbl: ReturnType<typeof useReactTable<any>>,
    colDefs: unknown[],
    loading: boolean,
  ) => (
    <Table>
      <colgroup>
        <col className="w-10" />
        <col className="w-[25%]" />
        <col className="w-[25%]" />
        <col className="w-[15%]" />
        <col className="w-[15%]" />
        <col className="w-16" />
        <col className="w-24" />
      </colgroup>
      <TableHeader>
        {tbl.getHeaderGroups().map((headerGroup) => (
          <TableRow key={headerGroup.id}>
            {headerGroup.headers.map((header) => (
              <TableHead key={header.id}>
                {header.isPlaceholder
                  ? null
                  : flexRender(
                      header.column.columnDef.header,
                      header.getContext(),
                    )}
              </TableHead>
            ))}
          </TableRow>
        ))}
      </TableHeader>
      <TableBody>
        {loading ? (
          <TableRow>
            <TableCell colSpan={colDefs.length} className="text-center py-8">
              Loading...
            </TableCell>
          </TableRow>
        ) : tbl.getRowModel().rows?.length ? (
          tbl.getRowModel().rows.map((row) => (
            <TableRow key={row.id} className="group/row">
              {row.getVisibleCells().map((cell) => (
                <TableCell key={cell.id}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </TableCell>
              ))}
            </TableRow>
          ))
        ) : (
          <TableEmpty key="empty" columnsLength={colDefs.length} />
        )}
      </TableBody>
    </Table>
  );

  return (
    <>
      <Card className="!shadow-none relative h-full bg-transparent overflow-hidden">
        <Spotlight />

        <ScrollArea className="size-full">
          <CardHeader className="space-y-0">
            <CardTitle className="mb-4">{t('admin.cacheManagement')}</CardTitle>

            {/* Stats Cards */}
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div className="rounded-lg border p-3 bg-bg-card">
                <div className="text-xs text-text-secondary mb-1">
                  {t('admin.l1Cache')}
                </div>
                <div className="text-xl font-bold">
                  {stats?.l1?.total_keys ?? '-'}
                </div>
                <div className="text-xs text-text-secondary">
                  {t('admin.totalKeys')} · {stats?.l1?.dialog_count ?? 0}{' '}
                  dialogs
                </div>
              </div>
              <div className="rounded-lg border p-3 bg-bg-card">
                <div className="text-xs text-text-secondary mb-1">
                  {t('admin.l2Cache')}
                </div>
                <div className="text-xl font-bold">
                  {stats?.l2?.total_entries ?? '-'}
                </div>
                <div className="text-xs text-text-secondary">
                  {t('admin.totalEntries')} · {stats?.l2?.indices?.length ?? 0}{' '}
                  indices
                </div>
              </div>
              <div className="rounded-lg border p-3 bg-bg-card">
                <div className="text-xs text-text-secondary mb-1">
                  {t('admin.redisStatus')}
                </div>
                <div className="flex items-center gap-2">
                  <Badge
                    variant={stats?.l1?.redis_alive ? 'success' : 'destructive'}
                  >
                    <LucideDot className="size-[1em] stroke-[8] mr-1" />
                    {stats?.l1?.redis_alive
                      ? t('admin.alive')
                      : t('admin.fail')}
                  </Badge>
                </div>
              </div>
            </div>

            {/* Tabs */}
            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <TabsList>
                <TabsTrigger value="l1">{t('admin.l1Entries')}</TabsTrigger>
                <TabsTrigger value="l2">{t('admin.l2Entries')}</TabsTrigger>
              </TabsList>

              {/* ═══ L1 Tab ═══ */}
              <TabsContent value="l1">
                <div className="flex items-center gap-3 flex-wrap mb-4">
                  <Select
                    value={l1DialogId || '__all__'}
                    onValueChange={(v) =>
                      setL1DialogId(v === '__all__' ? '' : v)
                    }
                  >
                    <SelectTrigger className="w-48 bg-bg-input border-border-button">
                      <SelectValue placeholder={t('admin.selectDialog')} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__all__">
                        {t('admin.allDialogs')}
                      </SelectItem>
                      {l1Dialogs?.map((dialog) => (
                        <SelectItem
                          key={dialog.dialog_id}
                          value={dialog.dialog_id}
                        >
                          {dialog.dialog_name || dialog.dialog_id.slice(0, 8)} (
                          {dialog.entry_count})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  <div className="ml-auto flex gap-2">
                    {l1SelectedRows.length > 0 && (
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => setL1DeleteModalOpen(true)}
                      >
                        <LucideTrash2 className="size-4 mr-1" />
                        {t('admin.delete')} ({l1SelectedRows.length})
                      </Button>
                    )}
                  </div>
                </div>

                {renderTable(l1Table, l1ColumnDefs, isLoadingL1)}

                <div className="flex items-center justify-end mt-4">
                  <RAGFlowPagination
                    total={l1Total}
                    current={l1Page}
                    pageSize={l1PageSize}
                    onChange={(p, ps) => {
                      setL1Page(p);
                      setL1PageSize(ps);
                    }}
                  />
                </div>
              </TabsContent>

              {/* ═══ L2 Tab ═══ */}
              <TabsContent value="l2">
                <div className="flex items-center gap-3 flex-wrap mb-4">
                  <Select
                    value={selectedTenantId}
                    onValueChange={(v) => {
                      setSelectedTenantId(v);
                      setSelectedDialogId('');
                    }}
                  >
                    <SelectTrigger className="w-48 bg-bg-input border-border-button">
                      <SelectValue placeholder={t('admin.selectTenant')} />
                    </SelectTrigger>
                    <SelectContent>
                      {tenants?.map((tenant) => (
                        <SelectItem
                          key={tenant.tenant_id}
                          value={tenant.tenant_id}
                        >
                          {tenant.tenant_name || tenant.tenant_id.slice(0, 8)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  <Select
                    value={selectedDialogId || '__all__'}
                    onValueChange={(v) =>
                      setSelectedDialogId(v === '__all__' ? '' : v)
                    }
                    disabled={!selectedTenantId}
                  >
                    <SelectTrigger className="w-48 bg-bg-input border-border-button">
                      <SelectValue placeholder={t('admin.selectDialog')} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__all__">
                        {t('admin.allDialogs')}
                      </SelectItem>
                      {dialogs?.map((dialog) => (
                        <SelectItem
                          key={dialog.dialog_id}
                          value={dialog.dialog_id}
                        >
                          {dialog.dialog_name || dialog.dialog_id.slice(0, 8)} (
                          {dialog.entry_count})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  <div className="relative w-56">
                    <LucideSearch className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 h-4 w-4" />
                    <Input
                      className="pl-10 h-10 bg-bg-input border-border-button"
                      placeholder={t('admin.searchByQuestion')}
                      value={questionSearch}
                      onChange={(e) => setQuestionSearch(e.target.value)}
                      disabled={!selectedTenantId}
                    />
                  </div>

                  <div className="ml-auto flex gap-2">
                    {selectedRows.length > 0 && (
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => setDeleteModalOpen(true)}
                      >
                        <LucideTrash2 className="size-4 mr-1" />
                        {t('admin.delete')} ({selectedRows.length})
                      </Button>
                    )}

                    {selectedDialogId && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="dark:bg-bg-input dark:border-border-button text-text-secondary"
                        onClick={() => setInvalidateModalOpen(true)}
                      >
                        <LucideEraser className="size-4 mr-1" />
                        {t('admin.invalidateL1')}
                      </Button>
                    )}

                    <Button
                      size="sm"
                      onClick={() => setCreateModalOpen(true)}
                      disabled={!selectedTenantId}
                    >
                      <LucidePlus className="size-4 mr-1" />
                      {t('admin.createCacheEntry')}
                    </Button>
                  </div>
                </div>

                {!selectedTenantId ? (
                  <div className="text-center py-12 text-text-secondary">
                    {t('admin.selectTenant')}
                  </div>
                ) : (
                  renderTable(l2Table, l2ColumnDefs, isLoadingEntries)
                )}

                {selectedTenantId && (
                  <div className="flex items-center justify-end mt-4">
                    <RAGFlowPagination
                      total={totalEntries}
                      current={page}
                      pageSize={pageSize}
                      onChange={(p, ps) => {
                        setPage(p);
                        setPageSize(ps);
                      }}
                    />
                  </div>
                )}
              </TabsContent>
            </Tabs>
          </CardHeader>
        </ScrollArea>
      </Card>

      {/* L2 Edit Modal */}
      <Dialog open={editModalOpen} onOpenChange={setEditModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('admin.editCacheEntry')}</DialogTitle>
          </DialogHeader>

          <section className="px-6 space-y-4">
            <div>
              <Label className="mb-2 block">{t('admin.question')}</Label>
              <div className="rounded-lg p-3 border bg-bg-card text-sm">
                {editEntry?.question_text}
              </div>
            </div>

            <div>
              <Label className="mb-2 block">{t('admin.answer')}</Label>
              <Textarea
                value={editAnswer}
                onChange={(e) => setEditAnswer(e.target.value)}
                rows={6}
              />
            </div>

            <div>
              <Label className="mb-2 block">{t('admin.ttlSeconds')}</Label>
              <Input
                type="number"
                value={editTTL}
                onChange={(e) => setEditTTL(e.target.value)}
                min={60}
              />
            </div>
          </section>

          <DialogFooter className="gap-4 px-6 py-4">
            <Button
              variant="outline"
              className="dark:border-border-button"
              onClick={() => setEditModalOpen(false)}
              disabled={updateMutation.isPending}
            >
              {t('admin.cancel')}
            </Button>
            <Button
              onClick={() => updateMutation.mutate()}
              disabled={updateMutation.isPending}
              loading={updateMutation.isPending}
            >
              {t('admin.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* L2 Create Modal */}
      <Dialog
        open={createModalOpen}
        onOpenChange={(open) => {
          setCreateModalOpen(open);
          if (!open) {
            setCreateQuestion('');
            setCreateAnswer('');
            setCreateTTL('5184000');
            setCreateDialogId('');
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('admin.createCacheEntry')}</DialogTitle>
          </DialogHeader>

          <section className="px-6 space-y-4">
            <div>
              <Label className="mb-2 block">{t('admin.dialog')}</Label>
              <Select
                value={createDialogId || selectedDialogId}
                onValueChange={setCreateDialogId}
              >
                <SelectTrigger className="bg-bg-input border-border-button">
                  <SelectValue placeholder={t('admin.selectDialog')} />
                </SelectTrigger>
                <SelectContent>
                  {dialogs?.map((dialog) => (
                    <SelectItem key={dialog.dialog_id} value={dialog.dialog_id}>
                      {dialog.dialog_name || dialog.dialog_id.slice(0, 8)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="mb-2 block">{t('admin.question')}</Label>
              <Textarea
                value={createQuestion}
                onChange={(e) => setCreateQuestion(e.target.value)}
                rows={3}
                placeholder={t('admin.searchByQuestion')}
              />
            </div>

            <div>
              <Label className="mb-2 block">{t('admin.answer')}</Label>
              <Textarea
                value={createAnswer}
                onChange={(e) => setCreateAnswer(e.target.value)}
                rows={6}
              />
            </div>

            <div>
              <Label className="mb-2 block">{t('admin.ttlSeconds')}</Label>
              <Input
                type="number"
                value={createTTL}
                onChange={(e) => setCreateTTL(e.target.value)}
                min={60}
              />
            </div>
          </section>

          <DialogFooter className="gap-4 px-6 py-4">
            <Button
              variant="outline"
              className="dark:border-border-button"
              onClick={() => setCreateModalOpen(false)}
              disabled={createMutation.isPending}
            >
              {t('admin.cancel')}
            </Button>
            <Button
              onClick={() => createMutation.mutate()}
              disabled={
                createMutation.isPending ||
                !createQuestion.trim() ||
                !createAnswer.trim() ||
                !(createDialogId || selectedDialogId)
              }
              loading={createMutation.isPending}
            >
              {t('admin.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* L2 Delete Confirmation Modal */}
      <Dialog open={deleteModalOpen} onOpenChange={setDeleteModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('admin.deleteCacheEntry')}</DialogTitle>
          </DialogHeader>

          <section className="px-6">
            <DialogDescription>
              {t('admin.deleteCacheEntryConfirmation')}
            </DialogDescription>
            <div className="rounded-lg mt-4 p-3 border bg-bg-card text-sm">
              {selectedRows.length} {t('admin.totalEntries').toLowerCase()}
            </div>
          </section>

          <DialogFooter className="gap-4 px-6 py-4">
            <Button
              variant="outline"
              className="dark:border-border-button"
              onClick={() => setDeleteModalOpen(false)}
              disabled={deleteMutation.isPending}
            >
              {t('admin.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
              loading={deleteMutation.isPending}
            >
              {t('admin.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* L1 Delete Confirmation Modal */}
      <Dialog open={l1DeleteModalOpen} onOpenChange={setL1DeleteModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('admin.deleteL1Entry')}</DialogTitle>
          </DialogHeader>

          <section className="px-6">
            <DialogDescription>
              {t('admin.deleteL1EntryConfirmation')}
            </DialogDescription>
            <div className="rounded-lg mt-4 p-3 border bg-bg-card text-sm">
              {l1SelectedRows.length} {t('admin.totalKeys').toLowerCase()}
            </div>
          </section>

          <DialogFooter className="gap-4 px-6 py-4">
            <Button
              variant="outline"
              className="dark:border-border-button"
              onClick={() => setL1DeleteModalOpen(false)}
              disabled={l1DeleteMutation.isPending}
            >
              {t('admin.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => l1DeleteMutation.mutate()}
              disabled={l1DeleteMutation.isPending}
              loading={l1DeleteMutation.isPending}
            >
              {t('admin.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Invalidate L1 Confirmation Modal */}
      <Dialog open={invalidateModalOpen} onOpenChange={setInvalidateModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('admin.invalidateL1')}</DialogTitle>
          </DialogHeader>

          <section className="px-6">
            <DialogDescription>
              {t('admin.invalidateL1Confirmation')}
            </DialogDescription>
          </section>

          <DialogFooter className="gap-4 px-6 py-4">
            <Button
              variant="outline"
              className="dark:border-border-button"
              onClick={() => setInvalidateModalOpen(false)}
              disabled={invalidateL1Mutation.isPending}
            >
              {t('admin.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => invalidateL1Mutation.mutate()}
              disabled={invalidateL1Mutation.isPending}
              loading={invalidateL1Mutation.isPending}
            >
              {t('admin.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

export default CacheManagement;
