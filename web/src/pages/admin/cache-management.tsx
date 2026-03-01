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
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
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
import { Textarea } from '@/components/ui/textarea';

import {
  createCacheL2Entry,
  deleteCacheL2Entries,
  getCacheStats,
  getCacheTenantDialogs,
  getCacheTenants,
  invalidateCacheL1Dialog,
  listCacheL2Entries,
  updateCacheL2Entry,
} from '@/services/admin-service';

const columnHelper = createColumnHelper<AdminService.CacheL2Entry>();

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

  // State
  const [selectedTenantId, setSelectedTenantId] = useState<string>('');
  const [selectedDialogId, setSelectedDialogId] = useState<string>('');
  const [questionSearch, setQuestionSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedRows, setSelectedRows] = useState<string[]>([]);

  // Modals
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editEntry, setEditEntry] = useState<AdminService.CacheL2Entry | null>(
    null,
  );
  const [editAnswer, setEditAnswer] = useState('');
  const [editTTL, setEditTTL] = useState('86400');

  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [createQuestion, setCreateQuestion] = useState('');
  const [createAnswer, setCreateAnswer] = useState('');
  const [createTTL, setCreateTTL] = useState('86400');
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

  // Read dialog_id from URL params
  useEffect(() => {
    const dialogIdParam = searchParams.get('dialog_id');
    if (dialogIdParam) {
      setSelectedDialogId(dialogIdParam);
    }
  }, [searchParams]);

  // Queries
  const { data: stats } = useQuery({
    queryKey: ['admin/cacheStats'],
    queryFn: async () => (await getCacheStats())?.data?.data,
    refetchInterval: 30000,
  });

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

  // Mutations
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
      setCreateTTL('86400');
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

  const invalidateL1Mutation = useMutation({
    mutationFn: async () => {
      if (!selectedDialogId) return;
      await invalidateCacheL1Dialog(selectedDialogId);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin/cacheStats'] });
      setInvalidateModalOpen(false);
    },
  });

  const handleEditClick = useCallback(
    (entry: AdminService.CacheL2Entry) => {
      setEditEntry(entry);
      setEditAnswer(entry.answer_json);
      setEditTTL(String(entry.ttl));
      setEditModalOpen(true);
    },
    [],
  );

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

  // Table columns
  const columnDefs = useMemo(
    () => [
      columnHelper.display({
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
      columnHelper.accessor('question_text', {
        header: t('admin.question'),
        cell: ({ cell }) => (
          <span title={cell.getValue()}>{truncate(cell.getValue(), 60)}</span>
        ),
      }),
      columnHelper.accessor('answer_json', {
        header: t('admin.answer'),
        cell: ({ cell }) => (
          <span title={cell.getValue()}>{truncate(cell.getValue(), 60)}</span>
        ),
      }),
      columnHelper.accessor('dialog_name', {
        header: t('admin.dialog'),
        cell: ({ cell, row }) => cell.getValue() || row.original.dialog_id,
      }),
      columnHelper.accessor('cached_at', {
        header: t('admin.cachedAt'),
        cell: ({ cell }) => formatTimestamp(cell.getValue()),
      }),
      columnHelper.accessor('ttl', {
        header: t('admin.ttl'),
        cell: ({ cell }) => formatTTL(cell.getValue()),
      }),
      columnHelper.display({
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

  const table = useReactTable({
    data: entries,
    columns: columnDefs,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: Math.ceil(totalEntries / pageSize),
  });

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
                  {t('admin.totalKeys')} ·{' '}
                  {stats?.l1?.dialog_count ?? 0} dialogs
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
                  {t('admin.totalEntries')} ·{' '}
                  {stats?.l2?.indices?.length ?? 0} indices
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

            {/* Filters */}
            <div className="flex items-center gap-3 flex-wrap">
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
                      {dialog.dialog_name ||
                        dialog.dialog_id.slice(0, 8)}{' '}
                      ({dialog.entry_count})
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
          </CardHeader>

          <CardContent>
            {!selectedTenantId ? (
              <div className="text-center py-12 text-text-secondary">
                {t('admin.selectTenant')}
              </div>
            ) : (
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
                  {table.getHeaderGroups().map((headerGroup) => (
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
                  {isLoadingEntries ? (
                    <TableRow>
                      <TableCell
                        colSpan={columnDefs.length}
                        className="text-center py-8"
                      >
                        Loading...
                      </TableCell>
                    </TableRow>
                  ) : table.getRowModel().rows?.length ? (
                    table.getRowModel().rows.map((row) => (
                      <TableRow key={row.id} className="group/row">
                        {row.getVisibleCells().map((cell) => (
                          <TableCell key={cell.id}>
                            {flexRender(
                              cell.column.columnDef.cell,
                              cell.getContext(),
                            )}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))
                  ) : (
                    <TableEmpty
                      key="empty"
                      columnsLength={columnDefs.length}
                    />
                  )}
                </TableBody>
              </Table>
            )}
          </CardContent>

          {selectedTenantId && (
            <CardFooter className="flex items-center justify-end">
              <RAGFlowPagination
                total={totalEntries}
                current={page}
                pageSize={pageSize}
                onChange={(p, ps) => {
                  setPage(p);
                  setPageSize(ps);
                }}
              />
            </CardFooter>
          )}
        </ScrollArea>
      </Card>

      {/* Edit Modal */}
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

      {/* Create Modal */}
      <Dialog
        open={createModalOpen}
        onOpenChange={(open) => {
          setCreateModalOpen(open);
          if (!open) {
            setCreateQuestion('');
            setCreateAnswer('');
            setCreateTTL('86400');
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
                    <SelectItem
                      key={dialog.dialog_id}
                      value={dialog.dialog_id}
                    >
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

      {/* Delete Confirmation Modal */}
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

      {/* Invalidate L1 Confirmation Modal */}
      <Dialog
        open={invalidateModalOpen}
        onOpenChange={setInvalidateModalOpen}
      >
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
