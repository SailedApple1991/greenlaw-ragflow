'use client';

import { AvatarUpload } from '@/components/avatar-upload';
import { KnowledgeBaseFormField } from '@/components/knowledge-base-item';
import { MetadataFilter } from '@/components/metadata-filter';
import { SwitchFormField } from '@/components/switch-fom-field';
import { TavilyFormField } from '@/components/tavily-form-field';
import { TOCEnhanceFormField } from '@/components/toc-enhance-form-field';
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Slider } from '@/components/ui/slider';
import { Textarea } from '@/components/ui/textarea';
import { useTranslate } from '@/hooks/common-hooks';
import { useFormContext, useWatch } from 'react-hook-form';

export default function ChatBasicSetting() {
  const { t } = useTranslate('chat');
  const form = useFormContext();
  const enableCache = useWatch({
    control: form.control,
    name: 'prompt_config.enable_cache',
  });

  return (
    <div className="space-y-8">
      <FormField
        control={form.control}
        name={'icon'}
        render={({ field }) => (
          <div className="space-y-6">
            <FormItem className="w-full">
              <FormLabel>{t('assistantAvatar')}</FormLabel>
              <FormControl>
                <AvatarUpload {...field}></AvatarUpload>
              </FormControl>
              <FormMessage />
            </FormItem>
          </div>
        )}
      />
      <FormField
        control={form.control}
        name="name"
        render={({ field }) => (
          <FormItem>
            <FormLabel required>{t('assistantName')}</FormLabel>
            <FormControl>
              <Input {...field}></Input>
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="description"
        render={({ field }) => (
          <FormItem>
            <FormLabel>{t('description')}</FormLabel>
            <FormControl>
              <Textarea {...field}></Textarea>
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name={'prompt_config.empty_response'}
        render={({ field }) => (
          <FormItem>
            <FormLabel tooltip={t('emptyResponseTip')}>
              {t('emptyResponse')}
            </FormLabel>
            <FormControl>
              <Textarea {...field}></Textarea>
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name={'prompt_config.prologue'}
        render={({ field }) => (
          <FormItem>
            <FormLabel tooltip={t('setAnOpenerTip')}>
              {t('setAnOpener')}
            </FormLabel>
            <FormControl>
              <Textarea {...field}></Textarea>
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <SwitchFormField
        name={'prompt_config.quote'}
        label={t('quote')}
        tooltip={t('quoteTip')}
      ></SwitchFormField>
      <SwitchFormField
        name={'prompt_config.keyword'}
        label={t('keyword')}
        tooltip={t('keywordTip')}
      ></SwitchFormField>
      <SwitchFormField
        name={'prompt_config.tts'}
        label={t('tts')}
        tooltip={t('ttsTip')}
      ></SwitchFormField>
      <SwitchFormField
        name={'prompt_config.enable_cache'}
        label={t('enableCache')}
        tooltip={t('enableCacheTip')}
      ></SwitchFormField>
      {enableCache && (
        <>
          <FormField
            control={form.control}
            name={'prompt_config.cache_ttl'}
            render={({ field }) => (
              <FormItem>
                <FormLabel tooltip={t('cacheTtlTip')}>
                  {t('cacheTtl')}
                </FormLabel>
                <FormControl>
                  <Input
                    type="number"
                    min={60}
                    max={604800}
                    {...field}
                    value={field.value ?? 86400}
                    onChange={(e) =>
                      field.onChange(parseInt(e.target.value, 10) || 86400)
                    }
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name={'prompt_config.cache_similarity_threshold'}
            render={({ field }) => (
              <FormItem>
                <FormLabel tooltip={t('cacheThresholdTip')}>
                  {t('cacheThreshold')}: {(field.value ?? 0.95).toFixed(2)}
                </FormLabel>
                <FormControl>
                  <Slider
                    min={0.8}
                    max={1.0}
                    step={0.01}
                    value={[field.value ?? 0.95]}
                    onValueChange={(vals) => field.onChange(vals[0])}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </>
      )}
      <TOCEnhanceFormField name="prompt_config.toc_enhance"></TOCEnhanceFormField>
      <TavilyFormField></TavilyFormField>
      <KnowledgeBaseFormField></KnowledgeBaseFormField>
      <MetadataFilter></MetadataFilter>
    </div>
  );
}
