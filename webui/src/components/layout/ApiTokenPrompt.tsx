import React, { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { setApiToken } from '@/lib/api';

export const ApiTokenPrompt: React.FC<{ open: boolean }> = ({ open }) => {
  const [value, setValue] = useState<string>('');

  const handleSave = () => {
    setApiToken(value.trim());
    window.location.reload();
  };

  return (
    <Dialog open={open}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>API Token Required</DialogTitle>
          <DialogDescription>
            Enter the shared API token (server EXIFTAGGER_API_TOKEN). It is stored only in
            this browser's localStorage.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <Input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="API token"
            className="font-mono text-sm"
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSave();
            }}
          />
          <Button onClick={handleSave} disabled={!value.trim()} className="w-full">
            Save Token
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default ApiTokenPrompt;
